import time

from odoo import api, fields, models


class PulseRateLimit(models.Model):
    _name = 'pulse.rate.limit'
    _description = 'LedgerPulse Rate Limit Bucket'

    api_key_id = fields.Many2one(
        'pulse.api.key', required=True, ondelete='cascade')
    minute_bucket = fields.Integer(required=True)
    hit_count = fields.Integer(default=0)

    # The unique constraint also creates the (api_key_id, minute_bucket) index,
    # so limit checks stay O(1).
    _sql_constraints = [
        ('key_bucket_uniq', 'unique(api_key_id, minute_bucket)',
         'One bucket per key per minute.'),
    ]

    @api.model
    def register_hit(self, api_key_id):
        """Atomically count one request; returns (hits_this_minute, bucket)."""
        bucket = int(time.time() // 60)
        self.env.cr.execute("""
            INSERT INTO pulse_rate_limit (api_key_id, minute_bucket, hit_count)
            VALUES (%s, %s, 1)
            ON CONFLICT (api_key_id, minute_bucket)
            DO UPDATE SET hit_count = pulse_rate_limit.hit_count + 1
            RETURNING hit_count
        """, (api_key_id, bucket))
        return self.env.cr.fetchone()[0], bucket

    @api.model
    def _gc_old_buckets(self):
        bucket = int(time.time() // 60)
        self.env.cr.execute(
            "DELETE FROM pulse_rate_limit WHERE minute_bucket < %s", (bucket - 60,))