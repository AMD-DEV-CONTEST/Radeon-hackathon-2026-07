/* Test Case 1: CWE-120 Buffer Overflow via gets() and strcpy()
 * Expected: 2+ critical/high risks
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* VULN: CWE-120 - gets() has no bounds checking */
void read_input() {
    char buf[64];
    gets(buf);  /* CRITICAL: stack buffer overflow */
    printf("You said: %s\n", buf);
}

/* VULN: CWE-120 - strcpy() does not check dest size */
void copy_data(char *src) {
    char dest[32];
    strcpy(dest, src);  /* HIGH: unbounded copy */
}

/* SAFE: uses fgets with size limit */
void safe_input() {
    char buf[64];
    fgets(buf, sizeof(buf), stdin);
}
