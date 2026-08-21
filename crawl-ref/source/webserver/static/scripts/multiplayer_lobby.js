define(["jquery", "comm"], function ($, comm) {
    "use strict";

    var client_id = null;
    var display_name = null;
    var rooms = [];
    var current_room = null;
    var peers = {};
    var channels = {};
    var pending_ice = {};
    var rtc_supported = ("RTCPeerConnection" in window);

    var mode_names = {
        standard: "일반",
        seeded: "지정 시드",
        descent: "디센트",
        sprint: "스프린트"
    };

    function send(message, data)
    {
        if (window.socket && socket.readyState === 1)
            comm.send_message(message, data);
    }

    function set_network_status(text, connected)
    {
        var badge = $("#room_network_status");
        badge.text(text)
            .toggleClass("room_badge_waiting", !connected)
            .toggleClass("room_badge_connected", connected);
    }

    function safe_store_name(name)
    {
        try { localStorage.setItem("dcss_room_name", name); }
        catch (error) { /* Private mode can disable localStorage. */ }
    }

    function stored_name()
    {
        try { return localStorage.getItem("dcss_room_name"); }
        catch (error) { return null; }
    }

    function world_summary(settings)
    {
        var summary = mode_names[settings.game_mode] || settings.game_mode;
        if (settings.seed)
            summary += " · 시드 " + settings.seed;
        summary += " · 턴 " + settings.turn_seconds + "초";
        summary += " · 이동 " + settings.transition_seconds + "초";
        return summary;
    }

    function room_state_text(room)
    {
        return room.state === "running" ? "진행 중 · 관전 가능" : "대기 중";
    }

    function make_button(label, class_name, handler)
    {
        return $("<button type='button'></button>")
            .addClass("room_button " + class_name)
            .text(label)
            .on("click", handler);
    }

    function render_rooms()
    {
        var list = $("#room_list").empty();
        var has_rooms = rooms.length > 0;
        $("#room_empty").toggle(!has_rooms);

        $.each(rooms, function (_, room) {
            var card = $("<article class='room_card'></article>");
            var top = $("<div class='room_card_top'></div>");
            var state = $("<span class='room_badge'></span>")
                .text(room_state_text(room))
                .toggleClass("room_badge_live", room.state === "running")
                .toggleClass("room_badge_waiting", room.state !== "running");
            top.append($("<h3></h3>").text(room.title), state);
            card.append(top);
            card.append($("<div class='room_card_host'></div>")
                .text("방장 · " + room.host_name));
            card.append($("<div class='room_card_meta'></div>")
                .append($("<span></span>").text(
                    "플레이어 " + room.player_count + "/" + room.settings.max_players))
                .append($("<span></span>").text(
                    "관전자 " + room.spectator_count))
                .append($("<span></span>").text("호스트 P2P")));
            card.append($("<div class='room_card_settings'></div>")
                .text(world_summary(room.settings)));

            var actions = $("<div class='room_card_actions'></div>");
            var join = make_button("플레이어 참가", "room_button_primary", function () {
                send("room_join", { room_id: room.id });
            });
            join.prop("disabled", !room.joinable || !!current_room);
            var watch = make_button("관전", "room_button_subtle", function () {
                send("room_watch", { room_id: room.id });
            });
            watch.prop("disabled", !!current_room);
            actions.append(watch, join);
            card.append(actions);
            list.append(card);
        });
    }

    function render_members(target, members, empty_text)
    {
        target.empty();
        if (!members.length)
        {
            target.append($("<li></li>").text(empty_text));
            return;
        }
        $.each(members, function (_, member) {
            var item = $("<li></li>").text(member.name);
            if (member.host)
                item.append($("<span class='room_host_mark'>방장</span>"));
            target.append(item);
        });
    }

    function add_setting(target, label, value)
    {
        target.append($("<div></div>")
            .append($("<dt></dt>").text(label))
            .append($("<dd></dd>").text(value)));
    }

    function render_current_room()
    {
        var panel = $("#room_current");
        panel.toggle(!!current_room);
        $("#room_browser").toggle(!current_room);
        $("#room_create_panel").hide();
        if (!current_room)
            return;

        $("#room_current_title").text(current_room.title);
        $("#room_current_state")
            .text(room_state_text(current_room))
            .toggleClass("room_badge_live", current_room.state === "running")
            .toggleClass("room_badge_waiting", current_room.state !== "running");
        $("#room_player_count").text(
            current_room.player_count + "/" + current_room.settings.max_players);
        $("#room_spectator_count").text(current_room.spectator_count);
        render_members($("#room_players"), current_room.players, "대기 중인 플레이어 없음");
        render_members($("#room_spectators"), current_room.spectators || [], "관전자 없음");

        var settings = $("#room_current_settings").empty();
        add_setting(settings, "게임 모드", mode_names[current_room.settings.game_mode]);
        add_setting(settings, "시드", current_room.settings.seed || "무작위");
        add_setting(settings, "턴 제한", current_room.settings.turn_seconds + "초");
        add_setting(settings, "맵 이동 대기", current_room.settings.transition_seconds + "초");

        var is_host = current_room.host_id === client_id;
        $("#room_start")
            .prop("disabled", false)
            .text("게임 시작")
            .toggle(is_host && current_room.state === "waiting");
        update_connection_summary();
    }

    function close_peer(peer_id)
    {
        if (channels[peer_id])
        {
            try { channels[peer_id].close(); } catch (error) {}
            delete channels[peer_id];
        }
        if (peers[peer_id])
        {
            try { peers[peer_id].close(); } catch (error) {}
            delete peers[peer_id];
        }
        delete pending_ice[peer_id];
        update_connection_summary();
    }

    function close_all_peers()
    {
        $.each(Object.keys(peers), function (_, peer_id) { close_peer(peer_id); });
    }

    function expected_peer_ids()
    {
        if (!current_room || current_room.state !== "running")
            return [];
        var members = (current_room.players || []).concat(current_room.spectators || []);
        if (current_room.host_id === client_id)
            return $.map(members, function (member) {
                return member.id !== client_id ? member.id : null;
            });
        return [current_room.host_id];
    }

    function update_connection_summary()
    {
        if (!current_room)
            return;
        var summary = $("#room_connection_summary");
        if (current_room.state !== "running")
        {
            summary.text("게임이 시작되면 방장 중심 WebRTC P2P 연결을 생성합니다.");
            return;
        }
        if (!rtc_supported)
        {
            summary.text("이 브라우저는 WebRTC P2P를 지원하지 않습니다.")
                .addClass("room_error");
            return;
        }
        summary.removeClass("room_error");
        var expected = expected_peer_ids();
        var connected = 0;
        $.each(expected, function (_, id) {
            if (channels[id] && channels[id].readyState === "open")
                connected++;
        });
        summary.text("P2P 직접 연결 " + connected + "/" + expected.length +
                     " · 게임 화면은 전용 서버가 중계합니다.");
    }

    function send_signal(peer_id, signal)
    {
        send("room_signal", { target_id: peer_id, signal: signal });
    }

    function setup_channel(peer_id, channel)
    {
        channels[peer_id] = channel;
        channel.onopen = function () {
            update_connection_summary();
            channel.send(JSON.stringify({
                type: "peer_ready",
                client_id: client_id,
                role: current_room ? current_room.self_role : null
            }));
        };
        channel.onclose = update_connection_summary;
        channel.onerror = update_connection_summary;
        channel.onmessage = function (event) {
            var payload;
            try { payload = JSON.parse(event.data); }
            catch (error) { return; }
            if (payload.type === "ping" && channel.readyState === "open")
                channel.send(JSON.stringify({ type: "pong" }));
        };
    }

    function new_peer(peer_id)
    {
        if (!rtc_supported)
            return null;
        if (peers[peer_id])
            return peers[peer_id];

        var peer = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });
        peers[peer_id] = peer;
        pending_ice[peer_id] = [];
        peer.onicecandidate = function (event) {
            if (event.candidate)
                send_signal(peer_id, { type: "ice", candidate: event.candidate });
        };
        peer.onconnectionstatechange = update_connection_summary;
        peer.ondatachannel = function (event) {
            setup_channel(peer_id, event.channel);
        };
        return peer;
    }

    function flush_ice(peer_id)
    {
        var peer = peers[peer_id];
        var queued = pending_ice[peer_id] || [];
        if (!peer || !peer.remoteDescription)
            return;
        pending_ice[peer_id] = [];
        $.each(queued, function (_, candidate) {
            peer.addIceCandidate(new RTCIceCandidate(candidate)).catch(function () {});
        });
    }

    function create_host_offer(peer_id)
    {
        var peer = new_peer(peer_id);
        if (!peer || channels[peer_id])
            return;
        var channel = peer.createDataChannel("crawl-room", { ordered: true });
        setup_channel(peer_id, channel);
        peer.createOffer()
            .then(function (offer) { return peer.setLocalDescription(offer); })
            .then(function () {
                send_signal(peer_id, { type: "offer", sdp: peer.localDescription });
            })
            .catch(function () { close_peer(peer_id); });
    }

    function sync_peers()
    {
        var expected = expected_peer_ids();
        $.each(Object.keys(peers), function (_, peer_id) {
            if (expected.indexOf(peer_id) === -1)
                close_peer(peer_id);
        });
        if (current_room && current_room.host_id === client_id)
            $.each(expected, function (_, peer_id) { create_host_offer(peer_id); });
        update_connection_summary();
    }

    function handle_signal(data)
    {
        if (!current_room || data.room_id !== current_room.id || !rtc_supported)
            return;
        var peer_id = data.from_id;
        var signal = data.signal;
        var peer = new_peer(peer_id);
        if (signal.type === "offer")
        {
            peer.setRemoteDescription(new RTCSessionDescription(signal.sdp))
                .then(function () { flush_ice(peer_id); return peer.createAnswer(); })
                .then(function (answer) { return peer.setLocalDescription(answer); })
                .then(function () {
                    send_signal(peer_id, { type: "answer", sdp: peer.localDescription });
                })
                .catch(function () { close_peer(peer_id); });
        }
        else if (signal.type === "answer")
        {
            peer.setRemoteDescription(new RTCSessionDescription(signal.sdp))
                .then(function () { flush_ice(peer_id); })
                .catch(function () { close_peer(peer_id); });
        }
        else if (signal.type === "ice")
        {
            if (peer.remoteDescription)
                peer.addIceCandidate(new RTCIceCandidate(signal.candidate)).catch(function () {});
            else
                pending_ice[peer_id].push(signal.candidate);
        }
    }

    function handle_hello(data)
    {
        client_id = data.client_id;
        display_name = data.display_name;
        set_network_status("전용 서버 연결됨", true);
        var saved = stored_name();
        if (saved && saved !== display_name)
            send("room_set_name", { name: saved });
        else
            $("#room_display_name").val(display_name);
        send("room_refresh");
    }

    function handle_room_list(data)
    {
        rooms = data.rooms || [];
        render_rooms();
    }

    function handle_room_state(data)
    {
        current_room = data.room;
        render_current_room();
        render_rooms();
        sync_peers();
    }

    function handle_room_joined(data)
    {
        current_room = data.room;
        $("#room_create_error").text("");
        render_current_room();
        render_rooms();
    }

    function clear_current_room(message)
    {
        close_all_peers();
        current_room = null;
        render_current_room();
        render_rooms();
        if (message)
            $("#room_identity_message").text(message).delay(3500).fadeOut(function () {
                $(this).show().text("");
            });
    }

    function handle_error(data)
    {
        $("#room_create_error").text(data.reason || "요청을 처리하지 못했습니다.");
        $("#room_identity_message").text(data.reason || "오류");
    }

    comm.register_handlers({
        room_hello: handle_hello,
        room_list: handle_room_list,
        room_joined: handle_room_joined,
        room_state: handle_room_state,
        room_signal: handle_signal,
        room_error: handle_error,
        room_name_set: function (data) {
            display_name = data.display_name;
            $("#room_display_name").val(display_name);
            $("#room_identity_message").text("닉네임을 저장했습니다.");
            safe_store_name(display_name);
        },
        room_started: function () {
            if (current_room)
            {
                current_room.state = "running";
                render_current_room();
            }
        },
        room_left: function () { clear_current_room("방에서 나왔습니다."); },
        room_closed: function (data) {
            clear_current_room(data.reason || "방이 종료되었습니다.");
        }
    });

    $(document).ready(function () {
        if (!$("#multiplayer_lobby").length)
            return;

        $("#room_save_name").on("click", function () {
            send("room_set_name", { name: $("#room_display_name").val() });
        });
        $("#room_display_name").on("keydown", function (event) {
            if (event.which === 13)
            {
                event.preventDefault();
                $("#room_save_name").click();
            }
        });
        $("#room_refresh").on("click", function () { send("room_refresh"); });
        $("#room_create_open").on("click", function () {
            $("#room_browser").hide();
            $("#room_create_panel").show();
            $("#room_title").focus();
        });
        $("#room_create_cancel").on("click", function () {
            $("#room_create_panel").hide();
            $("#room_browser").show();
        });
        $("#room_game_mode").on("change", function () {
            $("#room_seed_field").toggle($(this).val() === "seeded");
        });
        $("#room_create_form").on("submit", function (event) {
            event.preventDefault();
            $("#room_create_error").text("");
            send("room_create", {
                title: $("#room_title").val(),
                settings: {
                    game_mode: $("#room_game_mode").val(),
                    seed: $("#room_seed").val(),
                    turn_seconds: parseInt($("#room_turn_seconds").val(), 10),
                    transition_seconds: parseInt($("#room_transition_seconds").val(), 10),
                    max_players: parseInt($("#room_max_players").val(), 10)
                }
            });
        });
        $("#room_start").on("click", function () {
            $(this).prop("disabled", true).text("시작 중...");
            send("room_start");
        });
        $("#room_leave").on("click", function () { send("room_leave"); });

        window.addEventListener("beforeunload", close_all_peers);
        if (!rtc_supported)
            $("#room_identity_message").text("이 브라우저는 P2P 연결을 지원하지 않습니다.");
    });

    return {};
});
