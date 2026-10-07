import logging

_logger = logging.getLogger(__name__)


def _account(env, company, code, name, account_type):
    Account = env['account.account']
    acc = Account.search([('company_id', '=', company.id), ('code', '=', code)], limit=1)
    return acc or Account.create({
        'code': code, 'name': name, 'account_type': account_type, 'company_id': company.id})


def _tax(env, company, name, amount, price_include, account):
    Tax = env['account.tax']
    tax = Tax.search([('name', '=', name), ('company_id', '=', company.id)], limit=1)
    if tax:
        return tax

    def rep():
        return [
            (0, 0, {'repartition_type': 'base', 'factor_percent': 100.0}),
            (0, 0, {'repartition_type': 'tax', 'factor_percent': 100.0,
                    'account_id': account.id if amount else False}),
        ]
    return Tax.create({
        'name': name, 'amount': amount, 'amount_type': 'percent',
        'type_tax_use': 'sale', 'price_include': price_include,
        'company_id': company.id,
        'invoice_repartition_line_ids': rep(),
        'refund_repartition_line_ids': rep(),
    })


def ensure_demo_setup(env, company=None):
    """Idempotent: taxes, fiscal position, product, partners, payment term, EUR."""
    company = company or env.company
    env = env(context=dict(env.context, allowed_company_ids=[company.id]))
    tax_account = _account(env, company, 'PTAX01', 'Pulse Tax Payable', 'liability_current')
    vat = _tax(env, company, 'Pulse VAT 17%', 17.0, False, tax_account)
    vat_incl = _tax(env, company, 'Pulse VAT 17% (incl.)', 17.0, True, tax_account)
    zero = _tax(env, company, 'Pulse Exempt 0%', 0.0, False, tax_account)

    FP = env['account.fiscal.position']
    fp = FP.search([('name', '=', 'Pulse Tax Exempt'), ('company_id', '=', company.id)], limit=1)
    if not fp:
        fp = FP.create({
            'name': 'Pulse Tax Exempt', 'company_id': company.id,
            'tax_ids': [(0, 0, {'tax_src_id': vat.id, 'tax_dest_id': zero.id})],
        })

    Product = env['product.product'].with_company(company)
    product = Product.search([('default_code', '=', 'PULSE-SVC')], limit=1)
    if not product:
        product = Product.create({
            'name': 'LedgerPulse Services', 'default_code': 'PULSE-SVC',
            'type': 'service', 'list_price': 0.0, 'sale_ok': True,
            'taxes_id': [(6, 0, [vat.id])],
        })

    Partner = env['res.partner'].with_company(company)
    std = Partner.search([('name', '=', 'Pulse Standard Customer')], limit=1) or Partner.create({
        'name': 'Pulse Standard Customer', 'email': 'standard@pulse.example.com'})
    exempt = Partner.search([('name', '=', 'Pulse Exempt Customer')], limit=1) or Partner.create({
        'name': 'Pulse Exempt Customer', 'email': 'exempt@pulse.example.com'})
    if exempt.property_account_position_id != fp:
        exempt.property_account_position_id = fp

    term = env['account.payment.term'].search([('name', 'ilike', '30')], limit=1)

    eur = env['res.currency'].with_context(active_test=False).search([('name', '=', 'EUR')], limit=1)
    if eur and not eur.active:
        eur.active = True

    cfg = env['pulse.config'].get_config(company)
    vals = {}
    if not cfg.invoice_product_id:
        vals['invoice_product_id'] = product.id
    if not cfg.invoice_payment_term_id and term:
        vals['invoice_payment_term_id'] = term.id
    if vals:
        cfg.sudo().write(vals)

    return {
        'tax_account': tax_account, 'vat': vat, 'vat_incl': vat_incl, 'zero': zero,
        'fiscal_position': fp, 'product': product, 'standard_partner': std,
        'exempt_partner': exempt, 'payment_term': term, 'eur': eur,
    }


# ----------------------------------------------------------- analytic
def find_team_analytic_account(env, team, company):
    name = 'Pulse Team: %s' % (team.name if team else 'Unassigned')
    return env['account.analytic.account'].search([
        ('name', '=', name), ('company_id', 'in', [False, company.id])], limit=1)


def get_team_analytic_account(env, team, company):
    acc = find_team_analytic_account(env, team, company)
    if acc:
        return acc
    Plan = env['account.analytic.plan']
    plan = Plan.search([('parent_id', '=', False)], order='id', limit=1)
    if not plan:
        plan = Plan.create({'name': 'Projects'})
    name = 'Pulse Team: %s' % (team.name if team else 'Unassigned')
    return env['account.analytic.account'].create({
        'name': name, 'plan_id': plan.id, 'company_id': company.id})


# ----------------------------------------------------------- FX helpers
def set_rate(env, currency, company, date, rate):
    Rate = env['res.currency.rate']
    rec = Rate.search([('currency_id', '=', currency.id), ('name', '=', date),
                       ('company_id', '=', company.id)], limit=1)
    if rec:
        rec.rate = rate
    else:
        Rate.create({'currency_id': currency.id, 'name': date, 'rate': rate,
                     'company_id': company.id})


def fx_invoice_with_payment(env, partner, inv_date, pay_date, inv_rate, pay_rate, amount=1000.0):
    """EUR invoice posted at inv_rate, fully paid later at pay_rate."""
    company = env.company
    eur = env['res.currency'].with_context(active_test=False).search([('name', '=', 'EUR')], limit=1)
    if not eur.active:
        eur.active = True
    set_rate(env, eur, company, inv_date, inv_rate)
    set_rate(env, eur, company, pay_date, pay_rate)
    product = env['product.product'].search([('default_code', '=', 'PULSE-SVC')], limit=1)
    inv = env['account.move'].create({
        'move_type': 'out_invoice', 'partner_id': partner.id,
        'invoice_date': inv_date, 'currency_id': eur.id,
        'invoice_line_ids': [(0, 0, {
            'product_id': product.id, 'name': 'FX test service', 'quantity': 1,
            'price_unit': amount, 'tax_ids': [(6, 0, [])]})],
    })
    inv.action_post()
    pay = env['account.payment.register'].with_context(
        active_model='account.move', active_ids=inv.ids
    ).create({'payment_date': pay_date})._create_payments()
    return inv, pay