{
    'name': 'LedgerPulse',
    'version': '17.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Real-time CRM, OWL dashboard, REST API and full Accounting bridge',
    'description': """
LedgerPulse
===========
CRM + OWL + REST API + bus real-time + CRM-to-cash accounting bridge.
    """,
    'author': 'Muneeb Azam',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'crm', 'account', 'bus', 'web'],
    'data': [
        'security/pulse_security.xml',
        'security/ir.model.access.csv',
        'views/pulse_views.xml',
        'views/crm_lead_views.xml',
        'views/menu.xml',
        'views/pulse_phase6_views.xml',
        'views/pulse_phase8_12_views.xml',
        'data/pulse_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ledger_pulse/static/src/js/*.js',
            'ledger_pulse/static/src/xml/*.xml',
            'ledger_pulse/static/src/scss/*.scss',
        ],
    },
    'installable': True,
    'application': True,
}