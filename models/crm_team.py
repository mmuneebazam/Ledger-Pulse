from odoo import fields, models


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    pulse_source_channels = fields.Char(
        string='Pulse Source Channels',
        help="Comma separated source channels routed to this team, "
             "e.g. website,api. Used by the LedgerPulse assignment engine.")