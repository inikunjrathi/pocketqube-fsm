#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <zephyr/sys/crc.h>

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s <file>\n", argv[0]);
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (f == NULL) {
        perror("fopen");
        return 2;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        perror("fseek");
        fclose(f);
        return 2;
    }
    long len = ftell(f);
    if (len < 0) {
        perror("ftell");
        fclose(f);
        return 2;
    }
    rewind(f);

    uint8_t *buf = malloc((size_t)len > 0 ? (size_t)len : 1);
    if (buf == NULL) {
        fclose(f);
        return 2;
    }
    size_t nread = fread(buf, 1, (size_t)len, f);
    fclose(f);
    if (nread != (size_t)len) {
        free(buf);
        return 2;
    }

    uint32_t crc = crc32_ieee(buf, (size_t)len);
    printf("%08x\n", crc);

    free(buf);
    return 0;
}
