/** @odoo-module **/
import { EventBus } from "@odoo/owl";
import { registry } from "@web/core/registry";

// Subscribes to the Odoo bus ONCE and republishes to interested components.
export const pulseBusService = {
    dependencies: ["bus_service"],
    start(env, { bus_service }) {
        const bus = new EventBus();
        const channels = new Set();
        let subscribed = false;

        function ensureSubscribed() {
            if (subscribed) {
                return;
            }
            subscribed = true;
            bus_service.subscribe("ledger_pulse", (message) => bus.trigger("event", message));
            // After a reconnect we may have missed events: ask for a fresh snapshot.
            for (const name of ["reconnect", "connect"]) {
                try {
                    bus_service.addEventListener(name, () => bus.trigger("resync"));
                } catch (e) {
                    /* older bus API: ignore */
                }
            }
            window.addEventListener("online", () => bus.trigger("resync"));
        }

        return {
            bus,
            setChannels(list) {
                ensureSubscribed();
                for (const channel of list) {
                    if (!channels.has(channel)) {
                        channels.add(channel);
                        bus_service.addChannel(channel);
                    }
                }
                bus_service.start();
            },
        };
    },
};

registry.category("services").add("pulse_bus", pulseBusService);