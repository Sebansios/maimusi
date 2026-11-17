/*
 * hangul_core.h — C interface of the Hangul auto-spacing input method core.
 *
 * All strings are UTF-8 and NUL-terminated. Pointers inside hc_output stay
 * valid until the next call on the same session. Text offsets are UTF-16
 * code units. The library never logs, stores or transmits typed text; hc_session_take_learning
 * hands a hand-corrected boundary to the host, which decides whether to keep it.
 */
#ifndef HANGUL_CORE_H
#define HANGUL_CORE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct HcSession hc_session;
typedef struct HcSpacer hc_spacer;

enum {
    HC_KEY_CHAR = 0,        /* printable key; ch = character on US QWERTY with Shift applied */
    HC_KEY_SPACE = 1,
    HC_KEY_SHIFT_SPACE = 2, /* commit as typed (no automatic spacing), then a space */
    HC_KEY_BACKSPACE = 3,
    HC_KEY_ENTER = 4,
    HC_KEY_TAB = 5,
    HC_KEY_ESCAPE = 6,
    HC_KEY_LEFT = 7,
    HC_KEY_RIGHT = 8,
    HC_KEY_UP = 9,
    HC_KEY_DOWN = 10,
    HC_KEY_OTHER = 11,      /* any other key, or a key with Command/Control/Option */
    HC_KEY_SHRINK_SEGMENT = 12, /* Shift+Left while converting */
    HC_KEY_EXPAND_SEGMENT = 13, /* Shift+Right while converting */
    HC_KEY_MERGE_PREVIOUS = 14,
    HC_KEY_MERGE_NEXT = 15
};

enum {
    HC_SEGMENT_SHRINK = 1, HC_SEGMENT_EXPAND = 2,
    HC_SEGMENT_MERGE_PREVIOUS = 4, HC_SEGMENT_MERGE_NEXT = 8
};

/* Returns the spaced text or NULL when unavailable. The pointer must stay
 * valid until the callback is called again. */
typedef const char *(*hc_space_fn)(void *ctx, const char *text);
/* Returns newline-separated alternatives for one word, each optionally
 * followed by a tab and a short note naming its source; NULL/"" for none. */
typedef const char *(*hc_candidates_fn)(void *ctx, const char *word);

typedef struct {
    void *ctx;
    hc_space_fn space;
    hc_candidates_fn candidates;
} hc_backend;

typedef struct {
    bool consumed;            /* false: after inserting commit, pass the key to the app */
    const char *commit;       /* text to insert first, "" for none */
    const char *preedit;      /* marked text, "" for none */
    uint32_t preedit_utf16_len;
    int32_t highlight_start;  /* selected word in preedit, -1 for none */
    int32_t highlight_len;
    uint32_t candidate_count;
    int32_t candidate_index;  /* -1 when no candidate list is open */
} hc_output;

hc_session *hc_session_new(void);
void hc_session_free(hc_session *s);
/* Keys: layout (dubeolsik), convert_on_space, enter_passes_through,
 * space_implicit_commits ("1"/"0"), space_in_conversion (commit|cycle). */
bool hc_session_set_option(hc_session *s, const char *key, const char *value);
void hc_session_key(hc_session *s, uint32_t key, uint32_t ch, const hc_backend *backend, hc_output *out);
void hc_session_commit(hc_session *s, const hc_backend *backend, hc_output *out);
void hc_session_reset(hc_session *s, hc_output *out);
void hc_session_select_candidate(hc_session *s, uint32_t index, hc_output *out);
/* Available segment actions, a bitmask of HC_SEGMENT_*. Zero outside conversion. */
uint32_t hc_session_segment_actions(const hc_session *s);
/* Import a nonempty single-line document selection verbatim, only when idle.
 * out.consumed is false if rejected. No backend is called. On success the
 * host must replace exactly the selected UTF-16 range with out.preedit. */
void hc_session_edit_selection(hc_session *s, const char *text, hc_output *out);
const char *hc_session_candidate(const hc_session *s, uint32_t index);
const char *hc_session_candidate_note(const hc_session *s, uint32_t index);
/* After a commit of a conversion whose boundaries were edited by hand:
 * "proposed\x1faccepted" (same characters, different spaces), once. Else NULL.
 * The library does not keep it; the host decides whether to remember it. */
const char *hc_session_take_learning(hc_session *s);

/* 0 = Revised Romanization (2000), 1 = McCune-Reischauer, 2 = Yale. */
char *hc_romanize(const char *text, uint32_t system); /* free with hc_string_free */

hc_spacer *hc_spacer_load(const char *path);
void hc_spacer_free(hc_spacer *sp);
char *hc_spacer_space(const hc_spacer *sp, const char *text); /* free with hc_string_free */
void hc_string_free(char *p);

const char *hc_version(void);

#ifdef __cplusplus
}
#endif

#endif
