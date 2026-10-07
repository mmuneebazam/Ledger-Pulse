import hashlib
import hmac
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

ALLOWED_SCOPES = ['leads.read', 'leads.write', 'invoices.read', 'webhooks.write']


class PulseApiKey(models.Model):
    _name = 'pulse.api.key'
    _description = 'LedgerPulse API Key'

    name = fields.Char(required=True)
    key_prefix = fields.Char(readonly=True, copy=False, index=True)
    key_hash = fields.Char(readonly=True, copy=False)
    scopes = fields.Char(
        required=True, default='leads.read',
        help="Comma separated. Allowed: %s" % ', '.join(ALLOWED_SCOPES))
    partner_id = fields.Many2one('res.partner', ondelete='set null')
    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade',
        default=lambda self: self.env.company)
    expires_at = fields.Datetime()
    revoked = fields.Boolean(default=False)
    deprecated_until = fields.Datetime(
        help="Used by key rotation: old key keeps working until this moment.")
    last_used_at = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        ('key_prefix_uniq', 'unique(key_prefix)', 'API key prefix must be unique.'),
    ]

    # ---------- helpers ----------
    def _scope_list(self):
        self.ensure_one()
        return [s.strip() for s in (self.scopes or '').split(',') if s.strip()]

    @api.constrains('scopes')
    def _check_scopes(self):
        for rec in self:
            bad = set(rec._scope_list()) - set(ALLOWED_SCOPES)
            if bad:
                raise ValidationError(
                    _("Unknown scope(s): %s", ', '.join(sorted(bad))))

    @staticmethod
    def _hash_key(raw_key):
        # Keys are long random strings, so a plain SHA-256 is sufficient.
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def action_generate_key(self):
        self.ensure_one()
        raw = 'lp_' + secrets.token_urlsafe(32)
        self.write({
            'key_prefix': raw[:10],
            'key_hash': self._hash_key(raw),
            'revoked': False,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('API key generated - copy it NOW, it is shown only once'),
                'message': raw,
                'type': 'warning',
                'sticky': True,
            },
        }

    def action_revoke(self):
        self.write({'revoked': True})

    # ---------- used by the REST layer (Phase 3) ----------
    @api.model
    def authenticate(self, raw_key):
        """Return the matching valid key record, or an empty recordset."""
        empty = self.browse()
        if not raw_key or len(raw_key) < 10:
            return empty
        key = self.sudo().search([('key_prefix', '=', raw_key[:10])], limit=1)
        if not key or not key.key_hash:
            return empty
        if not hmac.compare_digest(key.key_hash, self._hash_key(raw_key)):
            return empty
        now = fields.Datetime.now()
        if key.revoked:
            return empty
        if key.expires_at and key.expires_at < now:
            return empty
        if key.deprecated_until and key.deprecated_until < now:
            return empty
        return key