/** @odoo-module **/
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { PulseKpiStrip, PulseLeadList, PulseToast } from "./pulse_components";

const CHANNELS = ["", "website", "api", "partner", "email", "phone", "other"];

export class PulseDashboard extends Component {
    static template = "ledger_pulse.PulseDashboard";
    static components = { PulseKpiStrip, PulseLeadList, PulseToast };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.pulseBus = useService("pulse_bus");
        this.channelOptions = CHANNELS;
        this.state = useState({
            snapshot: null,
            filters: { channel: "", min_score: 0 },
            toasts: [],
            now: Date.now(),
        });
        this._toastId = 0;
        this._refreshTimer = null;

        onWillStart(async () => {
            await this.loadSnapshot();
        });
        onMounted(() => {
            this.pulseBus.setChannels(this.state.snapshot.channels);
            this._tick = setInterval(() => (this.state.now = Date.now()), 15000);
        });
        onWillUnmount(() => {
            clearInterval(this._tick);
            clearTimeout(this._refreshTimer);
        });
        useBus(this.pulseBus.bus, "event", (ev) => this.onEvent(ev.detail));
        useBus(this.pulseBus.bus, "resync", () => this.loadSnapshot());
    }

    async loadSnapshot() {
        const filters = { ...this.state.filters };
        this.state.snapshot = await this.orm.call("pulse.dashboard", "get_snapshot", [], {
            filters,
        });
    }

    // Debounced re-fetch: keeps KPIs exact even under bursts of events.
    scheduleRefresh() {
        clearTimeout(this._refreshTimer);
        this._refreshTimer = setTimeout(() => this.loadSnapshot(), 800);
    }

    addToast(title, message, type) {
        const id = ++this._toastId;
        this.state.toasts.push({ id, title, message, type });
        setTimeout(() => this.dismissToast(id), 7000);
        if (this.state.toasts.length > 5) {
            this.state.toasts.shift();
        }
    }
    dismissToast(id) {
        const idx = this.state.toasts.findIndex((t) => t.id === id);
        if (idx >= 0) {
            this.state.toasts.splice(idx, 1);
        }
    }

    patchLead(p) {
        const lead = this.state.snapshot.leads.find((l) => l.id === p.id);
        if (lead) {
            Object.assign(lead, p);
        }
    }

    onEvent(msg) {
        const snap = this.state.snapshot;
        if (!snap) {
            return;
        }
        const p = msg.payload || {};
        switch (msg.event) {
            case "lead.created":
                if (!snap.leads.some((l) => l.id === p.id)) {
                    snap.leads.unshift({ invoice_badge: "none", ...p });
                    snap.leads.splice(60);
                }
                snap.kpis.new_leads_today += 1;
                if (p.score >= snap.high_score) {
                    this.addToast("High-score lead", `${p.name} (score ${p.score})`, "success");
                }
                break;
            case "lead.scored":
                this.patchLead(p);
                break;
            case "sla.breached":
                this.patchLead(p);
                snap.kpis.sla_breaches += 1;
                this.addToast("SLA breached", p.name, "danger");
                break;
            case "invoice.posted":
                this.addToast("Invoice posted", p.name || "", "info");
                break;
            case "payment.reconciled":
                this.addToast("Payment reconciled", p.name || "", "success");
                break;
            case "period.closed":
                snap.closed_periods.push(p.period);
                this.addToast("Period closed", p.period || "", "info");
                break;
        }
        this.scheduleRefresh();
    }

    onChannelChange(ev) {
        this.state.filters.channel = ev.target.value;
        this.loadSnapshot();
    }
    onMinScoreChange(ev) {
        this.state.filters.min_score = parseInt(ev.target.value || "0", 10) || 0;
        this.loadSnapshot();
    }
    openLead(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "crm.lead",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("ledger_pulse.dashboard", PulseDashboard);