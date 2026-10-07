/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { formatMoney, formatRemaining } from "./pulse_utils";

const BADGES = {
    none: ["No invoice", "secondary", "fa-minus"],
    draft: ["Draft", "secondary", "fa-pencil"],
    posted: ["Posted", "info", "fa-file-text-o"],
    partial: ["Partial", "warning", "fa-adjust"],
    in_payment: ["Awaiting bank", "info", "fa-hourglass-half"],
    paid: ["Paid", "success", "fa-check"],
    overdue: ["Overdue", "danger", "fa-exclamation-triangle"],
    cancel: ["Cancelled", "secondary", "fa-ban"],
};

export class PulseInvoiceStatusBadge extends Component {
    static template = "ledger_pulse.PulseInvoiceStatusBadge";
    static props = { state: String };
    get info() {
        const [label, color, icon] = BADGES[this.props.state] || BADGES.none;
        return { label, color, icon };
    }
}

export class PulseKpiStrip extends Component {
    static template = "ledger_pulse.PulseKpiStrip";
    static props = { kpis: Object, currency: Object, canSeeFinance: Boolean };
    money(value) {
        return formatMoney(value, this.props.currency);
    }
}

export class PulseLeadCard extends Component {
    static template = "ledger_pulse.PulseLeadCard";
    static components = { PulseInvoiceStatusBadge };
    static props = { lead: Object, currency: Object, now: Number, onOpen: Function };

    get money() {
        return formatMoney(this.props.lead.expected_revenue, this.props.currency);
    }
    get scoreColor() {
        const s = this.props.lead.score;
        return s >= 70 ? "success" : s >= 40 ? "warning" : "secondary";
    }
    // Breached / overdue are shown with icon + text + border, never colour alone.
    get sla() {
        const l = this.props.lead;
        if (l.sla_state === "breached") {
            return { cls: "o_pulse_breached", icon: "fa-exclamation-circle", text: "SLA BREACHED" };
        }
        if (l.sla_state === "ok" && l.sla_deadline) {
            const ms = new Date(l.sla_deadline).getTime() - this.props.now;
            return ms > 0
                ? { cls: "", icon: "fa-clock-o", text: `${formatRemaining(ms)} left` }
                : { cls: "o_pulse_breached", icon: "fa-exclamation-circle", text: "SLA DUE NOW" };
        }
        return { cls: "", icon: "fa-minus", text: "No SLA" };
    }
}

export class PulseLeadList extends Component {
    static template = "ledger_pulse.PulseLeadList";
    static components = { PulseLeadCard };
    static props = { leads: Array, currency: Object, now: Number, onOpen: Function };
    setup() {
        this.state = useState({ limit: 12 });
    }
    get visible() {
        return this.props.leads.slice(0, this.state.limit);
    }
    showMore() {
        this.state.limit += 12;
    }
}

export class PulseToast extends Component {
    static template = "ledger_pulse.PulseToast";
    static props = { toasts: Array, onDismiss: Function };
}