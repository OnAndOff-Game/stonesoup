define(["jquery", "comm", "client"], function ($, comm, client) {
    "use strict";

    var multiplayer = false;
    var current_turn = null;
    var turn_duration_ms = 0;
    var turn_deadline_ms = 0;
    var action_locked = false;
    var timer_id = null;
    var action_sequence = 0;

    function set_locked(locked)
    {
        action_locked = locked;
        $("#mobile-controls button[data-command]")
            .prop("disabled", locked || client.is_watching());
    }

    function set_status(text)
    {
        $("#mobile-turn-status").text(text);
    }

    function command_payload(raw_command)
    {
        var numeric = /^\d+$/.test(raw_command);
        if (numeric)
            return { kind: "key", keycode: parseInt(raw_command, 10) };
        return { kind: "text", text: raw_command };
    }

    function is_atomic_multiplayer_command(command)
    {
        if (command.kind !== "text" || command.text.length !== 1)
            return false;
        return "hjklybun.g<>".indexOf(command.text) !== -1;
    }

    function send_command(raw_command)
    {
        if (action_locked || client.is_watching())
            return;

        var command = command_payload(raw_command);
        if (multiplayer)
        {
            if (!is_atomic_multiplayer_command(command))
            {
                set_status("이 명령은 멀티플레이 턴 입력으로 아직 사용할 수 없습니다");
                return;
            }
            action_sequence += 1;
            comm.send_message("multiplayer_action", {
                turn: current_turn,
                request_id: current_turn + ":" + action_sequence,
                command: command,
            });
            set_locked(true);
            set_status("행동 제출됨 · 다른 플레이어 대기 중");
        }
        else if (command.kind === "key")
            comm.send_message("key", { keycode: command.keycode });
        else
            comm.send_message("text_input", { text: command.text });
    }

    function toggle_stats()
    {
        var open = !$(document.body).hasClass("mobile-stats-open");
        $(document.body).toggleClass("mobile-stats-open", open);
        $("#mobile-quick-actions button[data-panel=stats]")
            .attr("aria-expanded", open ? "true" : "false");
    }

    function update_timer()
    {
        if (!multiplayer || !turn_duration_ms)
            return;
        var remaining = Math.max(0, turn_deadline_ms - Date.now());
        $("#mobile-turn-progress").attr({
            max: turn_duration_ms,
            value: remaining,
        });
    }

    function handle_turn(data)
    {
        multiplayer = true;
        current_turn = data.turn;
        turn_duration_ms = Math.max(1, data.duration_ms || 1);
        turn_deadline_ms = Date.now() + Math.max(0, data.remaining_ms || 0);
        $("#mobile-turn-number").text("턴 " + current_turn);
        set_locked(!!data.submitted || data.phase !== "collecting");
        set_status(action_locked ? "다른 플레이어 대기 중" : "명령을 선택하세요");
        update_timer();
    }

    function handle_action_rejected(data)
    {
        if (data.turn !== current_turn)
            return;
        set_locked(false);
        set_status(data.message || "행동을 다시 선택하세요");
    }

    function handle_transition(data)
    {
        if (data.state === "pending")
            set_status("맵 이동 준비 · 계단 근처로 모이세요");
        else if (data.state === "cancel")
            set_status("멀리 있는 플레이어 때문에 이동이 취소됐습니다");
        else if (data.state === "commit")
            set_status("파티가 함께 다음 맵으로 이동합니다");
    }

    function init()
    {
        if (!$("#mobile-confirm-action").length)
        {
            $("<button>", {
                id: "mobile-confirm-action",
                type: "button",
                text: "\uD655\uC778",
            })
                .attr("data-command", "13")
                .insertBefore("#mobile-quick-actions button[data-panel=stats]");
        }

        $("#mobile-controls")
            .off("click.mobile_controls")
            .on("click.mobile_controls", "button[data-command]", function (ev) {
                ev.preventDefault();
                send_command(String($(this).data("command")));
            })
            .on("click.mobile_controls", "button[data-panel=stats]", function (ev) {
                ev.preventDefault();
                toggle_stats();
            });

        set_locked(false);
        if (timer_id === null)
            timer_id = window.setInterval(update_timer, 100);
    }

    function cleanup()
    {
        multiplayer = false;
        current_turn = null;
        action_locked = false;
        $(document.body).removeClass("mobile-stats-open");
        if (timer_id !== null)
        {
            window.clearInterval(timer_id);
            timer_id = null;
        }
    }

    $(document)
        .off("game_init.mobile_controls game_cleanup.mobile_controls")
        .on("game_init.mobile_controls", init)
        .on("game_cleanup.mobile_controls", cleanup);

    comm.register_handlers({
        "multiplayer_turn": handle_turn,
        "multiplayer_action_rejected": handle_action_rejected,
        "multiplayer_transition": handle_transition,
    });
});
