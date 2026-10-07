/** @odoo-module **/

// Shared currency helper: uses the company currency symbol/position/decimals
// sent by the server, so components never format money themselves.
export function formatMoney(amount, currency) {
    const decimals = currency && currency.decimals !== undefined ? currency.decimals : 2;
    const number = new Intl.NumberFormat(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    }).format(amount || 0);
    if (!currency || !currency.symbol) {
        return number;
    }
    return currency.position === "before"
        ? `${currency.symbol}\u00A0${number}`
        : `${number}\u00A0${currency.symbol}`;
}

export function formatRemaining(ms) {
    const totalMin = Math.floor(Math.abs(ms) / 60000);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
}