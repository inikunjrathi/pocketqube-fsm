#include "engine_arbitration.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_PENDING 64

int main(void)
{
    char line[4096];

    setvbuf(stdout, NULL, _IOLBF, 0);
    while (fgets(line, sizeof(line), stdin) != NULL) {
        engine_pending_event_t pending[MAX_PENDING];
        size_t order[MAX_PENDING];
        size_t n = 0;
        char *cursor = line;
        char *end;

        for (;;) {
            long ev = strtol(cursor, &end, 10);
            if (end == cursor) {
                break;
            }
            cursor = end;
            double ts = strtod(cursor, &end);
            if (end == cursor || ev < 0 || ev >= EVENT_COUNT || n == MAX_PENDING) {
                printf("ERROR malformed\n");
                n = (size_t)-1;
                break;
            }
            cursor = end;
            pending[n].event = (event_id_t)ev;
            pending[n].timestamp = ts;
            n++;
        }
        if (n == (size_t)-1) {
            continue;
        }
        engine_arbitrate(pending, n, order);
        printf("ORDER");
        for (size_t i = 0; i < n; i++) {
            printf(" %zu", order[i]);
        }
        printf("\n");
    }
    return 0;
}
