def _open_domain():
    return [('type', '=', 'opportunity'), ('active', '=', True), ('probability', '<', 100)]


def pick_team(env, channel, company):
    """Teams whose pulse_source_channels contains the channel.
    Tie-breaker: fewest open opportunities, then lowest team id."""
    teams = env['crm.team'].sudo().search([('company_id', 'in', [False, company.id])])
    cands = teams.filtered(lambda t: channel in [
        c.strip() for c in (t.pulse_source_channels or '').split(',') if c.strip()])
    if not cands:
        return env['crm.team']
    Lead = env['crm.lead'].sudo()
    load = {t.id: Lead.search_count(_open_domain() + [('team_id', '=', t.id)]) for t in cands}
    return min(cands, key=lambda t: (load[t.id], t.id))


def pick_user(env, team):
    """Team member with the fewest open opportunities, then lowest user id."""
    members = team.sudo().member_ids
    if not members:
        return env['res.users']
    Lead = env['crm.lead'].sudo()
    load = {u.id: Lead.search_count(_open_domain() + [('user_id', '=', u.id)]) for u in members}
    return min(members, key=lambda u: (load[u.id], u.id))


def assign(lead):
    company = lead.company_id or lead.env.company
    if not lead.team_id:
        team = pick_team(lead.env, lead.source_channel, company)
        if team:
            lead.team_id = team
    if lead.team_id and not lead.user_id:
        user = pick_user(lead.env, lead.team_id)
        if user:
            lead.user_id = user