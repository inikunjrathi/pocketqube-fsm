#include "engine_scheduler.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LINE_MAX_LEN 512

static char *next_token(char **cursor)
{
    char *p = *cursor;
    while (*p == ' ') {
        p++;
    }
    if (*p == '\0') {
        *cursor = p;
        return NULL;
    }
    char *start = p;
    while (*p != '\0' && *p != ' ' && *p != '\n') {
        p++;
    }
    if (*p != '\0') {
        *p = '\0';
        p++;
    }
    *cursor = p;
    return start;
}

static engine_scheduler_t g_sched;

static void reply_item(const engine_sched_item_t *item)
{
    if (item->has_deadline) {
        printf("OK id=%s data_class=%s size_bytes=%u deadline=%g\n",
               item->id, item->data_class, item->size_bytes, item->deadline);
    } else {
        printf("OK id=%s data_class=%s size_bytes=%u deadline=NONE\n",
               item->id, item->data_class, item->size_bytes);
    }
}

static void handle_reset(char *cursor)
{
    char *classes_tok = next_token(&cursor);
    if (classes_tok == NULL || next_token(&cursor) != NULL) {
        printf("ERROR bad_sched_reset_classes\n");
        return;
    }
    if (strcmp(classes_tok, "NONE") == 0) {
        engine_scheduler_init(&g_sched, NULL, 0);
        printf("OK\n");
        return;
    }
    const char *classes[ENGINE_SCHED_MAX_CLASSES];
    uint8_t n = 0;
    char *p = classes_tok;
    while (p != NULL) {
        if (n >= ENGINE_SCHED_MAX_CLASSES) {
            printf("ERROR bad_sched_reset_classes\n");
            return;
        }
        char *comma = strchr(p, ',');
        if (comma != NULL) {
            *comma = '\0';
        }
        if (*p == '\0' || strlen(p) >= ENGINE_SCHED_CLASS_NAME_MAX) {
            printf("ERROR bad_sched_reset_classes\n");
            return;
        }
        classes[n++] = p;
        p = (comma != NULL) ? comma + 1 : NULL;
    }
    engine_scheduler_init(&g_sched, classes, n);
    printf("OK\n");
}

static void handle_insert(char *cursor)
{
    char *id_tok = next_token(&cursor);
    char *class_tok = next_token(&cursor);
    char *size_tok = next_token(&cursor);
    char *deadline_tok = next_token(&cursor);
    if (id_tok == NULL || class_tok == NULL || size_tok == NULL || deadline_tok == NULL ||
        next_token(&cursor) != NULL) {
        printf("ERROR bad_sched_insert_args\n");
        return;
    }

    engine_sched_item_t item;
    memset(&item, 0, sizeof(item));
    if (strlen(id_tok) >= ENGINE_SCHED_ITEM_ID_MAX || strlen(class_tok) >= ENGINE_SCHED_CLASS_NAME_MAX) {
        printf("ERROR bad_sched_insert_args\n");
        return;
    }
    strcpy(item.id, id_tok);
    strcpy(item.data_class, class_tok);

    char *size_endptr = NULL;
    unsigned long size_val = strtoul(size_tok, &size_endptr, 10);
    if (size_endptr == size_tok || *size_endptr != '\0') {
        printf("ERROR bad_sched_size_bytes\n");
        return;
    }
    item.size_bytes = (uint32_t)size_val;

    if (strcmp(deadline_tok, "NONE") == 0) {
        item.has_deadline = false;
    } else {
        char *deadline_endptr = NULL;
        double deadline_val = strtod(deadline_tok, &deadline_endptr);
        if (deadline_endptr == deadline_tok || *deadline_endptr != '\0') {
            printf("ERROR bad_sched_deadline\n");
            return;
        }
        item.has_deadline = true;
        item.deadline = deadline_val;
    }

    engine_sched_status_t status = engine_scheduler_insert(&g_sched, &item);
    if (status == ENGINE_SCHED_ERR_UNKNOWN_CLASS) {
        printf("ERROR sched_unknown_class %s\n", item.data_class);
        return;
    }
    if (status == ENGINE_SCHED_ERR_QUEUE_FULL) {
        printf("ERROR sched_queue_full\n");
        return;
    }
    printf("OK\n");
}

static void handle_select(bool edf)
{
    engine_sched_item_t out;
    engine_sched_key_fn key = edf ? engine_scheduler_edf_key : NULL;
    if (engine_scheduler_select_next(&g_sched, key, &out)) {
        reply_item(&out);
    } else {
        printf("OK NONE\n");
    }
}

static void handle_peek_class(void)
{
    char class_buf[ENGINE_SCHED_CLASS_NAME_MAX];
    if (engine_scheduler_peek_next_class(&g_sched, class_buf, sizeof(class_buf))) {
        printf("OK data_class=%s\n", class_buf);
    } else {
        printf("OK NONE\n");
    }
}

static void handle_candidates(void)
{
    char classes[ENGINE_SCHED_QUEUE_CAPACITY][ENGINE_SCHED_CLASS_NAME_MAX];
    uint8_t n = engine_scheduler_candidate_classes(&g_sched, classes, ENGINE_SCHED_QUEUE_CAPACITY);
    if (n == 0) {
        printf("OK classes=NONE\n");
        return;
    }
    printf("OK classes=");
    for (uint8_t i = 0; i < n; i++) {
        if (i > 0) {
            printf(",");
        }
        printf("%s", classes[i]);
    }
    printf("\n");
}

static void handle_is_empty(void)
{
    printf("OK empty=%d\n", engine_scheduler_is_empty(&g_sched) ? 1 : 0);
}

static void handle_all_items(void)
{
    engine_sched_item_t items[ENGINE_SCHED_QUEUE_CAPACITY];
    uint8_t n = engine_scheduler_all_items(&g_sched, items, ENGINE_SCHED_QUEUE_CAPACITY);
    if (n == 0) {
        printf("OK ids=NONE\n");
        return;
    }
    printf("OK ids=");
    for (uint8_t i = 0; i < n; i++) {
        if (i > 0) {
            printf(",");
        }
        printf("%s", items[i].id);
    }
    printf("\n");
}

int main(void)
{
    char line[LINE_MAX_LEN];

    while (fgets(line, sizeof(line), stdin) != NULL) {
        char *cursor = line;
        char *tag_tok = next_token(&cursor);
        if (tag_tok == NULL) {
            continue;
        }
        if (strcmp(tag_tok, "SCHED") != 0) {
            printf("ERROR bad_harness_line\n");
            fflush(stdout);
            continue;
        }
        char *op_tok = next_token(&cursor);
        if (op_tok == NULL) {
            printf("ERROR bad_harness_line\n");
        } else if (strcmp(op_tok, "RESET") == 0) {
            handle_reset(cursor);
        } else if (strcmp(op_tok, "INSERT") == 0) {
            handle_insert(cursor);
        } else if (strcmp(op_tok, "SELECT") == 0) {
            handle_select(false);
        } else if (strcmp(op_tok, "SELECT_EDF") == 0) {
            handle_select(true);
        } else if (strcmp(op_tok, "PEEK_CLASS") == 0) {
            handle_peek_class();
        } else if (strcmp(op_tok, "CANDIDATES") == 0) {
            handle_candidates();
        } else if (strcmp(op_tok, "IS_EMPTY") == 0) {
            handle_is_empty();
        } else if (strcmp(op_tok, "ALL_ITEMS") == 0) {
            handle_all_items();
        } else {
            printf("ERROR bad_harness_op\n");
        }
        fflush(stdout);
    }
    return 0;
}
