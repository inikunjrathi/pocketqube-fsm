#include "engine_auth.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LINE_MAX_LEN 512
#define MAX_SECRET_BYTES 256

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

static long hex_decode(const char *hex, uint8_t *out, size_t out_cap)
{
    size_t len = strlen(hex);
    if (len % 2 != 0) {
        return -1;
    }
    size_t n = len / 2;
    if (n > out_cap) {
        return -1;
    }
    for (size_t i = 0; i < n; i++) {
        int hi = hex_nibble(hex[2 * i]);
        int lo = hex_nibble(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            return -1;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return (long)n;
}

static int split_fields(char *line, char *fields[], int max_fields)
{
    int count = 0;
    char *cursor = line;
    while (count < max_fields) {
        fields[count] = cursor;
        count++;
        char *bar = strchr(cursor, '|');
        if (bar == NULL) {
            break;
        }
        *bar = '\0';
        cursor = bar + 1;
    }
    return count;
}

static void handle_sign(int case_no, char *fields[4])
{
    const char *event_id = fields[1];
    char *end = NULL;
    double now = strtod(fields[2], &end);
    if (end == fields[2]) {
        printf("SIGN %d ERROR malformed_now\n", case_no);
        return;
    }

    uint8_t secret[MAX_SECRET_BYTES];
    long secret_len = hex_decode(fields[3], secret, sizeof(secret));
    if (secret_len < 0) {
        printf("SIGN %d ERROR malformed_secret_hex\n", case_no);
        return;
    }

    char out_hex[ENGINE_AUTH_SIGNATURE_HEX_LEN + 1];
    bool ok = engine_auth_sign_command(event_id, now, secret, (size_t)secret_len, out_hex);
    if (!ok) {
        printf("SIGN %d ERROR sign_failed\n", case_no);
        return;
    }
    printf("SIGN %d RESULT %s\n", case_no, out_hex);
}

static void handle_verify(int case_no, char *fields[5])
{
    const char *event_id = fields[1];
    char *end = NULL;
    double now = strtod(fields[2], &end);
    if (end == fields[2]) {
        printf("VERIFY %d ERROR malformed_now\n", case_no);
        return;
    }

    uint8_t secret[MAX_SECRET_BYTES];
    long secret_len = hex_decode(fields[3], secret, sizeof(secret));
    if (secret_len < 0) {
        printf("VERIFY %d ERROR malformed_secret_hex\n", case_no);
        return;
    }

    const char *signature = (strcmp(fields[4], "NULL") == 0) ? NULL : fields[4];

    engine_auth_set_secret(secret, (size_t)secret_len);
    bool result = engine_auth_verify_command(event_id, now, signature);
    printf("VERIFY %d RESULT %s\n", case_no, result ? "true" : "false");
}

int main(void)
{

    setvbuf(stdout, NULL, _IOLBF, 0);

    char line[LINE_MAX_LEN];
    int case_no = 0;
    while (fgets(line, sizeof(line), stdin) != NULL) {
        size_t len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
            line[--len] = '\0';
        }
        if (len == 0) {
            continue;
        }

        char *fields[5];
        int nfields = split_fields(line, fields, 5);

        if (nfields >= 1 && strcmp(fields[0], "SIGN") == 0 && nfields == 4) {
            handle_sign(case_no, fields);
        } else if (nfields >= 1 && strcmp(fields[0], "VERIFY") == 0 && nfields == 5) {
            handle_verify(case_no, fields);
        } else {
            printf("? %d ERROR malformed_line\n", case_no);
        }
        case_no++;
    }
    return 0;
}
