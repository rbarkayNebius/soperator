/* Execute a program on behalf of pam_exec(8) with an environment this helper
 * fully controls.
 *
 * pam_exec builds its child's environment from pam_getenvlist() plus the PAM_*
 * items. Session modules that run earlier in the stack may have put
 * user-authored variables there (pam_env's deprecated user_readenv reads the
 * authenticating user's ~/.pam_environment, which in the login container lives
 * in the user's own writable jail home). The hooks pam_exec starts run as uid 0
 * before the jail pivot, and both the dynamic loader and the shell take
 * code-loading directives from their environment (LD_PRELOAD, LD_AUDIT,
 * BASH_ENV, PATH, ...), so such a variable would be arbitrary root code
 * execution.
 *
 * This helper therefore drops every inherited variable, keeps a fixed PATH and
 * forwards only the PAM_* items, then executes the requested program. It is
 * linked statically so that its own startup consults nothing from the inherited
 * environment either.
 */

#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static char clean_path[] = "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin";

/* Only the three items pam_exec always exports, because pam_exec appends an
 * item solely when the application set it: a name the application leaves unset
 * (PAM_RUSER, and PAM_TTY or PAM_RHOST depending on the flow) has no
 * authoritative occurrence, so its only value would be the user-authored one.
 * PAM_AUTHTOK is absent for a different reason: an authentication token must
 * not leak into a hook's environment. */
static const char *const forwarded_variables[] = {
    "PAM_TYPE",
    "PAM_USER",
    "PAM_SERVICE",
};

#define FORWARDED_VARIABLE_COUNT (sizeof(forwarded_variables) / sizeof(forwarded_variables[0]))

/* pam_exec appends its own PAM_* items after the entries taken from
 * pam_getenvlist(), so for an item the application set, keeping the last
 * occurrence of the name discards a user-authored duplicate that would
 * otherwise shadow the authoritative value - glibc's getenv() returns the first
 * one instead, which is why the child must not be left to look them up itself.
 */
static char *last_occurrence(char **environment, const char *name)
{
    const size_t name_length = strlen(name);
    char *found = NULL;
    char **entry;

    for (entry = environment; entry != NULL && *entry != NULL; ++entry) {
        if (strncmp(*entry, name, name_length) == 0 && (*entry)[name_length] == '=') {
            found = *entry;
        }
    }

    return found;
}

/* Exits 0 on every failure path: pam_exec hooks must never block a login. The
 * diagnostics go to stderr, which pam_exec redirects to its log= target. */
int main(int argc, char **argv, char **environment)
{
    /* One slot per forwarded variable, one for clean_path, one for the
     * terminating NULL. */
    char *clean_environment[FORWARDED_VARIABLE_COUNT + 2];
    size_t clean_count = 0;
    size_t i;

    if (argc < 2 || argv[1][0] != '/') {
        (void)fprintf(stderr, "pam_exec_clean_env: usage: pam_exec_clean_env /path/to/program [argument...]\n");
        return 0;
    }

    clean_environment[clean_count++] = clean_path;
    for (i = 0; i < FORWARDED_VARIABLE_COUNT; ++i) {
        char *entry = last_occurrence(environment, forwarded_variables[i]);

        if (entry != NULL) {
            clean_environment[clean_count++] = entry;
        }
    }
    clean_environment[clean_count] = NULL;

    (void)execve(argv[1], argv + 1, clean_environment);
    (void)fprintf(stderr, "pam_exec_clean_env: execute %s: %s\n", argv[1], strerror(errno));

    return 0;
}
