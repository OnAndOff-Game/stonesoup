/**
 * @file
 * @brief Korean translation helpers for messages and UI strings.
 */

#include "AppHdr.h"

#include "korean-localisation.h"

#include "database.h"
#include "options.h"
#include "stringutil.h"

static string _translate_exact(const string &text)
{
    string translated = getTranslatedString(text);
    trim_string_right(translated);
    return translated == text ? "" : translated;
}

static string _translate_preserving_space(const string &text)
{
    string translated = _translate_exact(text);
    if (!translated.empty())
        return translated;

    const string trimmed = trimmed_string(text);
    if (trimmed.empty() || trimmed == text)
        return text;

    // Colour-tag contents such as "?" are controls, not prose. Looking up
    // punctuation by itself can collide with unrelated prompt translations.
    bool has_word_character = false;
    for (const unsigned char c : trimmed)
    {
        if (isalnum(c) || c >= 0x80)
        {
            has_word_character = true;
            break;
        }
    }
    if (!has_word_character)
        return text;

    translated = _translate_exact(trimmed);
    if (translated.empty())
        return text;

    const size_t start = text.find(trimmed);
    return text.substr(0, start) + translated
           + text.substr(start + trimmed.length());
}

string korean_translate(const string &text)
{
    if (Options.language != lang_t::KO || text.empty())
        return text;

    string translated = _translate_preserving_space(text);
    if (translated != text)
        return translated;

    // A large amount of menu text is wrapped in colour tags after it is
    // assembled. Translate only the literal regions and leave tags intact.
    string result;
    size_t pos = 0;
    while (pos < text.length())
    {
        const size_t tag = text.find('<', pos);
        const size_t end = tag == string::npos ? string::npos
                                               : text.find('>', tag + 1);
        if (tag == string::npos || end == string::npos)
        {
            result += _translate_preserving_space(text.substr(pos));
            break;
        }

        result += _translate_preserving_space(text.substr(pos, tag - pos));
        result += text.substr(tag, end - tag + 1);
        pos = end + 1;
    }
    return result;
}
