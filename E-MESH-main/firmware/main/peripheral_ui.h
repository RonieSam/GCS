/**
 * @file peripheral_ui.h
 * @brief LED, Buzzer, and SOS Button driver interface.
 *
 * The SOS button uses a hardware interrupt (ISR) for instant response.
 * LED and Buzzer are controlled via simple on/off and pattern functions.
 */

#pragma once

#include <stdbool.h>

#define BUZZER_BEEP_SHORT_MS 100

/**
 * @brief Initialize all UI peripherals (LED, Buzzer, SOS button).
 *
 * Configures GPIO pins and installs the SOS button interrupt handler.
 * Safe to call even if peripherals are not physically connected.
 */
void ui_init(void);

/* ── LED Control ────────────────────────────────────────────────────────── */

void led_on(void);
void led_off(void);
void led_toggle(void);

/**
 * @brief Start a repeating LED blink pattern.
 * @param on_ms  Duration LED is on (milliseconds).
 * @param off_ms Duration LED is off (milliseconds).
 */
void led_blink_start(int on_ms, int off_ms);

/** @brief Stop the blinking pattern and turn LED off. */
void led_blink_stop(void);

/* ── Buzzer Control ─────────────────────────────────────────────────────── */

void buzzer_on(void);
void buzzer_off(void);

/**
 * @brief Play a single beep.
 * @param duration_ms How long the buzzer sounds.
 */
void buzzer_beep(int duration_ms);

/**
 * @brief Start a repeating buzzer alarm pattern.
 * @param on_ms  Duration buzzer is on (milliseconds).
 * @param off_ms Duration buzzer is off (milliseconds).
 */
void buzzer_alarm_start(int on_ms, int off_ms);

/** @brief Stop the buzzer alarm pattern. */
void buzzer_alarm_stop(void);

/* ── SOS Button ─────────────────────────────────────────────────────────── */

/**
 * @brief Check if the SOS button was pressed (clears the flag).
 *
 * Uses a hardware interrupt internally. This function is safe to call
 * from any task context. It returns true once per physical press
 * (with debouncing).
 *
 * @return true if the SOS button was pressed since the last check.
 */
bool sos_button_pressed(void);

/**
 * @brief Activate the SOS emergency pattern (continuous LED + buzzer).
 *
 * Starts rapid LED blinking and continuous buzzer alarm.
 */
void sos_activate_alarm(void);

/**
 * @brief Deactivate the SOS emergency pattern.
 *
 * Stops the LED and buzzer alarm.
 */
void sos_deactivate_alarm(void);
