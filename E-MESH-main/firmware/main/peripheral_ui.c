/**
 * @file peripheral_ui.c
 * @brief LED, Buzzer, and SOS Button driver implementation.
 *
 * SOS button uses gpio_isr_handler for instant, zero-latency detection.
 * LED and Buzzer patterns run on a dedicated FreeRTOS task using
 * esp_timer for precise non-blocking timing.
 */

#include "peripheral_ui.h"
#include "board_config.h"
#include "sdkconfig.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "UI";

/* ── Internal State ─────────────────────────────────────────────────────── */

/* SOS button interrupt flag (set in ISR, cleared by sos_button_pressed) */
static volatile bool s_sos_flag = false;
static int64_t       s_sos_last_isr_time = 0;

/* LED blink state */
static esp_timer_handle_t s_led_timer = NULL;
static bool s_led_blinking = false;
static int  s_led_on_ms  = 500;
static int  s_led_off_ms = 500;
static bool s_led_state  = false;

/* Buzzer alarm state */
static esp_timer_handle_t s_buzzer_timer = NULL;
static bool s_buzzer_alarming = false;
static int  s_buzzer_on_ms  = 500;
static int  s_buzzer_off_ms = 500;
static bool s_buzzer_state  = false;

/* ── ISR Handler ────────────────────────────────────────────────────────── */

static void IRAM_ATTR sos_isr_handler(void *arg)
{
    /* Debounce: ignore interrupts within SOS_DEBOUNCE_MS of the last one */
    int64_t now = esp_timer_get_time(); /* microseconds */
    if ((now - s_sos_last_isr_time) > (SOS_DEBOUNCE_MS * 1000)) {
        s_sos_flag = true;
        s_sos_last_isr_time = now;
    }
}

/* ── Timer Callbacks ────────────────────────────────────────────────────── */

static void led_timer_callback(void *arg)
{
    s_led_state = !s_led_state;
    gpio_set_level(PIN_LED, s_led_state ? 1 : 0);

    /* Adjust next period based on current state */
    int next_period_ms = s_led_state ? s_led_on_ms : s_led_off_ms;
    esp_timer_stop(s_led_timer);
    esp_timer_start_once(s_led_timer, next_period_ms * 1000);
}

static void buzzer_timer_callback(void *arg)
{
    s_buzzer_state = !s_buzzer_state;
    gpio_set_level(PIN_BUZZER, s_buzzer_state ? 1 : 0);

    int next_period_ms = s_buzzer_state ? s_buzzer_on_ms : s_buzzer_off_ms;
    esp_timer_stop(s_buzzer_timer);
    esp_timer_start_once(s_buzzer_timer, next_period_ms * 1000);
}

/* ── Initialization ─────────────────────────────────────────────────────── */

void ui_init(void)
{
    /* ── LED GPIO ── */
    gpio_config_t led_cfg = {
        .pin_bit_mask = (1ULL << PIN_LED),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&led_cfg);
    gpio_set_level(PIN_LED, 0);
    ESP_LOGI(TAG, "LED initialized on GPIO %d", PIN_LED);

    /* ── Buzzer GPIO ── */
    gpio_config_t buzzer_cfg = {
        .pin_bit_mask = (1ULL << PIN_BUZZER),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&buzzer_cfg);
    gpio_set_level(PIN_BUZZER, 0);
    ESP_LOGI(TAG, "Buzzer initialized on GPIO %d", PIN_BUZZER);

    /* ── SOS Button GPIO (active LOW with internal pull-up) ── */
#ifdef CONFIG_EMESH_SOS_ENABLED
    gpio_config_t sos_cfg = {
        .pin_bit_mask = (1ULL << PIN_SOS_BUTTON),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_NEGEDGE, /* Trigger on press (HIGH → LOW) */
    };
    gpio_config(&sos_cfg);

    /* Install ISR service and attach handler */
    gpio_install_isr_service(0);
    gpio_isr_handler_add(PIN_SOS_BUTTON, sos_isr_handler, NULL);
    ESP_LOGI(TAG, "SOS button initialized on GPIO %d (ISR active)", PIN_SOS_BUTTON);
#else
    ESP_LOGI(TAG, "SOS button support disabled in menuconfig.");
#endif

    /* ── Create timers for LED/Buzzer patterns ── */
    esp_timer_create_args_t led_timer_args = {
        .callback = led_timer_callback,
        .name     = "led_blink",
    };
    esp_timer_create(&led_timer_args, &s_led_timer);

    esp_timer_create_args_t buzzer_timer_args = {
        .callback = buzzer_timer_callback,
        .name     = "buzzer_alarm",
    };
    esp_timer_create(&buzzer_timer_args, &s_buzzer_timer);

    ESP_LOGI(TAG, "UI peripherals initialized.");
}

/* ── LED Control ────────────────────────────────────────────────────────── */

void led_on(void)
{
    led_blink_stop();
    gpio_set_level(PIN_LED, 1);
}

void led_off(void)
{
    led_blink_stop();
    gpio_set_level(PIN_LED, 0);
}

void led_toggle(void)
{
    s_led_state = !s_led_state;
    gpio_set_level(PIN_LED, s_led_state ? 1 : 0);
}

void led_blink_start(int on_ms, int off_ms)
{
    if (s_led_blinking) {
        esp_timer_stop(s_led_timer);
    }
    s_led_on_ms  = on_ms;
    s_led_off_ms = off_ms;
    s_led_state  = true;
    s_led_blinking = true;

    gpio_set_level(PIN_LED, 1);
    esp_timer_start_once(s_led_timer, on_ms * 1000);
}

void led_blink_stop(void)
{
    if (s_led_blinking) {
        esp_timer_stop(s_led_timer);
        s_led_blinking = false;
    }
    gpio_set_level(PIN_LED, 0);
    s_led_state = false;
}

/* ── Buzzer Control ─────────────────────────────────────────────────────── */

void buzzer_on(void)
{
    buzzer_alarm_stop();
    gpio_set_level(PIN_BUZZER, 1);
}

void buzzer_off(void)
{
    buzzer_alarm_stop();
    gpio_set_level(PIN_BUZZER, 0);
}

void buzzer_beep(int duration_ms)
{
    gpio_set_level(PIN_BUZZER, 1);
    vTaskDelay(pdMS_TO_TICKS(duration_ms));
    gpio_set_level(PIN_BUZZER, 0);
}

void buzzer_alarm_start(int on_ms, int off_ms)
{
    if (s_buzzer_alarming) {
        esp_timer_stop(s_buzzer_timer);
    }
    s_buzzer_on_ms  = on_ms;
    s_buzzer_off_ms = off_ms;
    s_buzzer_state  = true;
    s_buzzer_alarming = true;

    gpio_set_level(PIN_BUZZER, 1);
    esp_timer_start_once(s_buzzer_timer, on_ms * 1000);
}

void buzzer_alarm_stop(void)
{
    if (s_buzzer_alarming) {
        esp_timer_stop(s_buzzer_timer);
        s_buzzer_alarming = false;
    }
    gpio_set_level(PIN_BUZZER, 0);
    s_buzzer_state = false;
}

/* ── SOS Button ─────────────────────────────────────────────────────────── */

bool sos_button_pressed(void)
{
    if (s_sos_flag) {
        s_sos_flag = false;
        return true;
    }
    return false;
}

void sos_activate_alarm(void)
{
    ESP_LOGW(TAG, "⚠ SOS ALARM ACTIVATED");
    led_blink_start(LED_BLINK_FAST_MS, LED_BLINK_FAST_MS);
    buzzer_alarm_start(BUZZER_BEEP_LONG_MS, BUZZER_BEEP_SHORT_MS);
}

void sos_deactivate_alarm(void)
{
    ESP_LOGI(TAG, "SOS alarm deactivated.");
    led_blink_stop();
    buzzer_alarm_stop();
}
