# -*- coding: utf-8 -*-
# Copyright (c) 2018, Libermatic and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils \
    import flt, add_days, add_months, get_last_day, getdate, formatdate
from functools import partial, reduce
from gwi_customization.microfinance.api.loan import get_outstanding_principal
from gwi_customization.microfinance.utils import calc_interest
from gwi_customization.microfinance.utils.fp import update, join, compose


def _interest_to_period(interest):
    billed_amount = flt(interest.get('billed_amount'))
    paid_amount = flt(interest.get('paid_amount'))
    return {
        'period_label': interest.get('period'),
        'start_date': interest.get('start_date'),
        'end_date': interest.get('end_date'),
        'billed_amount': billed_amount,
        'outstanding_amount': billed_amount - paid_amount,
    }


def _allocate(period, amount):
    outstanding_amount = flt(period.get('outstanding_amount'))
    allocated_amount = outstanding_amount \
        if outstanding_amount < amount else amount
    period.update({
        'allocated_amount': allocated_amount
    })
    return period


def _generate_periods(init_date, interest_amount):
    start_date = getdate(init_date)
    while True:
        end_date = get_last_day(start_date)
        yield {
            'period_label': start_date.strftime('%b %Y'),
            'start_date': start_date,
            'end_date': end_date,
            'billed_amount': interest_amount,
            'outstanding_amount': interest_amount,
        }
        start_date = add_days(end_date, 1)


def get_unpaid(loan):
    return frappe.db.sql(
        """
            SELECT
                loan, posting_date, period, start_date, end_date,
                billed_amount, paid_amount
            FROM `tabMicrofinance Loan Interest`
            WHERE loan='{loan}' AND status != 'Clear'
            ORDER BY start_date
        """.format(loan=loan),
        as_dict=True,
    )


def get_last_paid(loan):
    res = frappe.db.sql(
        """
            SELECT
                loan, posting_date, period, start_date, end_date,
                billed_amount, paid_amount
            FROM `tabMicrofinance Loan Interest`
            WHERE loan='{loan}' AND status = 'Clear'
            ORDER BY start_date DESC
            LIMIT 1
        """.format(loan=loan),
        as_dict=True,
    )
    return res[0] if res else None


def allocate_interests(loan, posting_date, amount_to_allocate):
    periods = []
    to_allocate = amount_to_allocate

    existing_unpaid_interests = get_unpaid(loan)
    for period in map(_interest_to_period, existing_unpaid_interests):
        p = _allocate(period, to_allocate)
        periods.append(p)
        to_allocate -= p.get('allocated_amount')

    calculation_slab, loan_date, rate_of_interest = frappe.get_value(
        'Microfinance Loan',
        loan,
        ['calculation_slab', 'posting_date', 'rate_of_interest'],
    )
    outstanding_amount = get_outstanding_principal(loan, posting_date)
    interest_amount = calc_interest(
        outstanding_amount, rate_of_interest, calculation_slab
    )
    last = get_last_paid(loan)
    effective_date = frappe.get_value(
        'Microfinance Loan Settings', None, 'effective_date'
    )
    init_date = add_days(periods[-1].get('end_date'), 1) if periods \
        else add_days(last.get('end_date'), 1) if last \
        else max(loan_date, getdate(effective_date))
    gen_per = _generate_periods(init_date, interest_amount)
    while to_allocate > 0:
        per = _allocate(gen_per.next(), to_allocate)
        periods.append(per)
        to_allocate -= per.get('allocated_amount')
    return periods


@frappe.whitelist()
def get_current_interest(loan, posting_date):
    outstanding = get_outstanding_principal(loan, posting_date)
    calculation_slab, rate_of_interest = frappe.get_value(
        'Microfinance Loan',
        loan,
        ['calculation_slab', 'rate_of_interest'],
    )
    return calc_interest(
        outstanding, rate_of_interest, calculation_slab
    )


def make_name(loan, start_date):
    return loan + '/' + formatdate(start_date, 'YYYY-MM')


def get_fine_write_off(interest):
    wo_amounts = frappe.get_all(
        'Microfinance Write Off',
        filters={
            'docstatus': 1,
            'write_off_type': 'Fine',
            'reference_doc': interest,
        },
        fields=['amount']
    )
    return reduce(lambda a, x: a + x.get('amount'), wo_amounts, 0)


def _make_list_item(row):
    fine_wrote_off = get_fine_write_off(row.name) > 0 if row.fine_amount \
        else False
    return update({
        'outstanding_amount': row.billed_amount - row.paid_amount,
        'fine_wrote_off': fine_wrote_off,
    })(row)


def _gen_dates(from_date, to_date):
    current_date = getdate(from_date)
    while current_date <= getdate(to_date):
        yield current_date
        current_date = add_months(current_date, 1)


@frappe.whitelist()
def list(loan, from_date, to_date):
    if getdate(to_date) < getdate(from_date):
        return frappe.throw('To date cannot be less than From date')

    conds = [
        "loan = '{}'".format(loan),
        "docstatus = 1",
        "start_date BETWEEN '{}' AND '{}'".format(from_date, to_date),
    ]
    existing = frappe.db.sql(
        """
            SELECT
                name, status,
                period, posting_date, start_date,
                billed_amount, paid_amount, fine_amount
            FROM `tabMicrofinance Loan Interest` WHERE {conds}
        """.format(
            conds=join(" AND ")(conds)
        ),
        as_dict=True,
    )
    existing_dict = dict((row.name, row) for row in existing)

    get_item = compose(existing_dict.get, partial(make_name, loan))
    make_item = compose(_make_list_item, get_item)
    loan_date = frappe.get_value('Microfinance Loan', loan, 'posting_date')

    def make_empty(d):
        return {
            'name': make_name(loan, d),
            'period': d.strftime('%b %Y'),
            'start_date': max(loan_date, d),
            'status': 'Unbilled'
        }

    dates = compose(
        partial(_gen_dates, to_date=to_date), partial(max, loan_date), getdate,
    )(from_date)

    effective_date = frappe.get_value(
        'Microfinance Loan Settings', None, 'effective_date'
    )
    is_not_sys_mgr = 'System Manager' not in frappe.permissions.get_roles()

    def change_status(row):
        start_date = row.get('start_date')
        status = 'Clear' \
            if is_not_sys_mgr \
            and getdate(effective_date) > getdate(start_date) \
            else row.get('status')
        return update({
            'status': status,
        })(row)

    return compose(
        partial(map, change_status),
        partial(map, lambda x: make_item(x) if get_item(x) else make_empty(x)),
    )(dates)


@frappe.whitelist()
def create(loan, period, start_date, billed_amount=None):
    if 'Loan Manager' not in frappe.permissions.get_roles():
        return frappe.throw('Insufficient permission')
    prev = compose(
        partial(frappe.db.exists, 'Microfinance Loan Interest'),
        partial(make_name, loan),
        getdate,
        partial(add_months, months=-1),
    )(start_date)
    if not prev:
        if 'System Manager' not in frappe.permissions.get_roles():
            return frappe.throw('Only System Managers can execute this')
        return frappe.throw('Interest for previous interval does not exists')
    end_date = compose(get_last_day, getdate)(start_date)
    interest = frappe.get_doc({
        'doctype': 'Microfinance Loan Interest',
        'loan': loan,
        'posting_date': add_days(end_date, 1),
        'period': period,
        'start_date': getdate(start_date),
        'end_date': end_date,
        'billed_amount': billed_amount,
    })
    interest.insert()
    interest.submit()
    return interest


def _has_next_interest(interest):
    return compose(
        partial(frappe.db.exists, 'Microfinance Loan Interest'),
        partial(make_name, interest.loan),
        partial(add_months, months=1),
    )(interest.start_date)


@frappe.whitelist()
def edit(name, billed_amount=0):
    if 'Loan Manager' not in frappe.permissions.get_roles():
        return frappe.throw('Insufficient permission')
    if not billed_amount:
        return frappe.throw('Billed amount cannot be zero')
    interest = frappe.get_doc('Microfinance Loan Interest', name)
    if _has_next_interest(interest):
        return frappe.throw('Interest for next interval already exists')
    interest.run_method('update_billed_amount', billed_amount)
    return interest


@frappe.whitelist()
def clear(name):
    if 'Loan Manager' not in frappe.permissions.get_roles():
        return frappe.throw('Insufficient permission')
    interest = frappe.get_doc('Microfinance Loan Interest', name)
    if _has_next_interest(interest):
        return frappe.throw('Interest for next interval already exists')
    interest.run_method('update_billed_amount', interest.paid_amount)
    return interest


@frappe.whitelist()
def remove(name):
    if 'Loan Manager' not in frappe.permissions.get_roles():
        return frappe.throw('Insufficient permission')
    interest = frappe.get_doc('Microfinance Loan Interest', name)
    if _has_next_interest(interest):
        return frappe.throw('Interest for next interval already exists')
    interest.cancel()
    frappe.delete_doc('Microfinance Loan Interest', name)
    return interest


@frappe.whitelist()
def fine(name):
    if 'Loan Manager' not in frappe.permissions.get_roles():
        return frappe.throw('Insufficient permission')
    interest = frappe.get_doc('Microfinance Loan Interest', name)
    loan_start_date = frappe.get_value(
        'Microfinance Loan', interest.loan, 'posting_date'
    )
    prev_status = compose(
        partial(
            frappe.get_value, 'Microfinance Loan Interest', fieldname='status'
        ),
        partial(make_name, interest.loan),
        partial(add_months, months=-1),
    )(interest.end_date) if interest.start_date > loan_start_date else 'Clear'
    if prev_status not in ['Clear', 'Fined']:
        return frappe.throw('Previous interest is not cleared or fined')
    if _has_next_interest(interest):
        return frappe.throw('Interest for next interval already exists')
    interest.run_method('set_fine_amount')
    return interest


@frappe.whitelist()
def unfine(name):
    if 'Loan Manager' not in frappe.permissions.get_roles():
        return frappe.throw('Insufficient permission')
    interest = frappe.get_doc('Microfinance Loan Interest', name)
    if not interest.fine_amount:
        return frappe.throw('No late fines to undo')
    if _has_next_interest(interest):
        return frappe.throw('Interest for next interval already exists')
    write_off = frappe.get_doc({
        'doctype': 'Microfinance Write Off',
        'loan': interest.loan,
        'posting_date': add_months(interest.end_date, 1),
        'amount': interest.fine_amount,
        'reason': 'Late fine reversed for {}'.format(interest.period),
        'write_off_type': 'Fine',
        'reference_doc': interest.name,
    })
    write_off.insert()
    write_off.submit()
    return interest
