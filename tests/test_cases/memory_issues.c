/* Test Case 5: Memory Management Issues
 * Expected: 1-2 medium risks
 */

#include <stdlib.h>
#include <stdio.h>

/* VULN: CWE-476 - malloc() without NULL check */
void allocate_and_use() {
    char *buf = malloc(1024);  /* MEDIUM: no NULL check */
    sprintf(buf, "data");      /* potential NULL deref */
    free(buf);
}

/* VULN: CWE-415 - double free */
void cleanup(char *ptr) {
    free(ptr);    /* first free */
    free(ptr);    /* HIGH: double free */
}

/* SAFE: checks return value */
void safe_allocate() {
    char *buf = malloc(1024);
    if (buf == NULL) {
        return;
    }
    sprintf(buf, "data");
    free(buf);
}
