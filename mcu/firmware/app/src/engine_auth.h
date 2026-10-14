#ifndef ENGINE_AUTH_H
#define ENGINE_AUTH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ENGINE_AUTH_SIGNATURE_HEX_LEN 64u

#define ENGINE_AUTH_SECRET_MAX_LEN 64u

bool engine_auth_verify_command(const char *event_id, double now, const char *hex_signature_or_null);

void engine_auth_set_secret(const uint8_t *secret, size_t secret_len);

bool engine_auth_has_secret_provisioned(void);

bool engine_auth_sign_command(const char *event_id, double now,
                               const uint8_t *secret, size_t secret_len,
                               char out_hex[ENGINE_AUTH_SIGNATURE_HEX_LEN + 1]);

#ifdef __cplusplus
}
#endif

#endif
