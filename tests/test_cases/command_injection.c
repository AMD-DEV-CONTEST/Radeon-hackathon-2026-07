/* Test Case 2: CWE-78 Command Injection
 * Expected: 2+ high risks (system, os.system equivalent)
 */

#include <stdlib.h>
#include <stdio.h>

/* VULN: CWE-78 - system() with user input */
void run_command(char *user_input) {
    char cmd[256];
    sprintf(cmd, "echo %s", user_input);  /* also CWE-134 */
    system(cmd);  /* HIGH: command injection */
}

/* VULN: CWE-78 - direct system() call */
void ping_host(char *host) {
    char buf[128];
    snprintf(buf, sizeof(buf), "ping -c 1 %s", host);
    system(buf);  /* HIGH: command injection */
}
