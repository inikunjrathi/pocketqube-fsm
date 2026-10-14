#include "engine_auth.h"

#include <mbedtls/md.h>

#include <stdio.h>
#include <string.h>

static uint8_t g_secret[ENGINE_AUTH_SECRET_MAX_LEN];
static size_t g_secret_len;

#define ENGINE_AUTH_MESSAGE_BUF_SIZE 128u

static bool now_is_signable(double now, long long *out_int_now)
{
    if (!(now >= 0.0) || !(now < 1e15)) {
        return false;
    }
    long long int_now = (long long)now;

    if ((double)int_now != now) {
        return false;
    }
    *out_int_now = int_now;
    return true;
}

static void hex_encode_lower(const uint8_t *bytes, size_t len, char *out)
{
    static const char digits[] = "0123456789abcdef";

    for (size_t i = 0; i < len; i++) {
        out[2 * i] = digits[(bytes[i] >> 4) & 0x0F];
        out[2 * i + 1] = digits[bytes[i] & 0x0F];
    }
    out[2 * len] = '\0';
}

static bool constant_time_hex_equal(const char *a, const char *b)
{
    unsigned char diff = 0;

    for (size_t i = 0; i < ENGINE_AUTH_SIGNATURE_HEX_LEN; i++) {
        diff |= (unsigned char)a[i] ^ (unsigned char)b[i];
    }
    return diff == 0;
}

bool engine_auth_sign_command(const char *event_id, double now,
                               const uint8_t *secret, size_t secret_len,
                               char out_hex[ENGINE_AUTH_SIGNATURE_HEX_LEN + 1])
{
    if (event_id == NULL || out_hex == NULL) {
        return false;
    }
    if (secret == NULL && secret_len != 0) {
        return false;
    }

    long long int_now = 0;

    if (!now_is_signable(now, &int_now)) {
        return false;
    }

    char message[ENGINE_AUTH_MESSAGE_BUF_SIZE];
    int written = snprintf(message, sizeof(message), "%s:%lld.0", event_id, int_now);

    if (written < 0 || (size_t)written >= sizeof(message)) {
        return false;
    }

    const mbedtls_md_info_t *md_info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);

    if (md_info == NULL) {
        return false;
    }

    uint8_t digest[32];
    int rc = mbedtls_md_hmac(md_info, secret, secret_len,
                              (const unsigned char *)message, (size_t)written, digest);

    if (rc != 0) {
        return false;
    }

    hex_encode_lower(digest, sizeof(digest), out_hex);
    return true;
}

void engine_auth_set_secret(const uint8_t *secret, size_t secret_len)
{
    if (secret == NULL || secret_len == 0 || secret_len > ENGINE_AUTH_SECRET_MAX_LEN) {
        g_secret_len = 0;
        return;
    }
    memcpy(g_secret, secret, secret_len);
    g_secret_len = secret_len;
}

bool engine_auth_has_secret_provisioned(void)
{
    return g_secret_len > 0;
}

bool engine_auth_verify_command(const char *event_id, double now, const char *hex_signature_or_null)
{
    if (hex_signature_or_null == NULL) {
        return false;
    }
    if (g_secret_len == 0) {
        return false;
    }
    if (strlen(hex_signature_or_null) != ENGINE_AUTH_SIGNATURE_HEX_LEN) {

        return false;
    }

    char expected_hex[ENGINE_AUTH_SIGNATURE_HEX_LEN + 1];

    if (!engine_auth_sign_command(event_id, now, g_secret, g_secret_len, expected_hex)) {
        return false;
    }

    return constant_time_hex_equal(expected_hex, hex_signature_or_null);
}
