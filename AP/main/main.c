#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_mac.h"

#define BLINK_GPIO GPIO_NUM_2

static const char *TAG = "blink";

void app_main(void)
{
    /* Configure the IOMUX register for pad BLINK_GPIO (some boards may need this) */
    gpio_reset_pin(BLINK_GPIO);
    gpio_set_direction(BLINK_GPIO, GPIO_MODE_OUTPUT);

    while (1) {
        gpio_set_level(BLINK_GPIO, 0); // LED off
        ESP_LOGI(TAG, "LED OFF");
        vTaskDelay(pdMS_TO_TICKS(500));

        gpio_set_level(BLINK_GPIO, 1); // LED on
        ESP_LOGI(TAG, "LED ON");
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}