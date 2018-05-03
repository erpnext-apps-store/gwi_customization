# -*- coding: utf-8 -*-
# Copyright (c) 2018, Libermatic and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe.utils import add_days, get_last_day, getdate, flt, fmt_money
from frappe.contacts.doctype.address.address import get_default_address
from functools import reduce, partial
from gwi_customization.microfinance.utils.fp import join, pick
from gwi_customization.microfinance.api.loan import (
    get_chart_data,
    calculate_principal,
    get_outstanding_principal,
)


def _make_address_text(customer=None):
    """Returns formatted address of Customer"""
    if not customer:
        return None
    address = frappe.get_value(
        'Address',
        get_default_address('Customer', customer),
        ['address_line1', 'city'],
        as_dict=True
    )
    if not address:
        return None
    return join(', ')([address.get('address_line1'), address.get('city')])


def _fmt_money(amount):
    return fmt_money(
        amount,
        precision=0,
        currency=frappe.defaults.get_user_default('currency'),
    )


def _existing_loans_by(customer):
    return frappe.get_all(
        'Microfinance Loan',
        filters=[
            ['docstatus', '=', '1'],
            ['customer', '=', customer],
            ['recovery_status', 'in', 'Not Started, In Progress'],
        ]
    )


def _reduce_outstanding_by(posting_date):
    def fn(a, x):
        return a + partial(
            get_outstanding_principal, posting_date=posting_date
        )(x)
    return fn


class MicrofinanceLoan(Document):
    def validate(self):
        if self.recovery_amount > self.loan_principal:
            frappe.throw("Recovery Amount cannot exceed Principal.")
        self.validate_allowable_amount()

    def validate_allowable_amount(self):
        effective_date = frappe.get_value(
            'Loan Plan', self.loan_plan, 'effective_from'
        )
        if effective_date and \
                getdate(effective_date) > getdate(self.posting_date):
            return None

        date_of_retirement, net_salary_amount = frappe.get_value(
            'Microfinance Loanee',
            {'customer': self.customer},
            ['date_of_retirement', 'net_salary_amount']
        )
        if not date_of_retirement or not net_salary_amount:
            return None
        allowed = calculate_principal(
            income=net_salary_amount,
            loan_plan=self.loan_plan,
            end_date=date_of_retirement,
            execution_date=self.posting_date,
        )
        if self.loan_principal > flt(allowed.get('principal')):
            frappe.throw(
                "Requested principal cannot exceed {}".format(
                    _fmt_money(allowed.get('principal'))
                )
            )
        if self.recovery_amount \
                < self.loan_principal / allowed.get('duration'):
            frappe.throw(
                "Recovery Amount cannot be less than {}".format(
                    _fmt_money(self.loan_principal / allowed.get('duration'))
                )
            )
        tentative_outstanding = reduce(
            _reduce_outstanding_by(self.posting_date),
            map(pick('name'), _existing_loans_by(self.customer)),
            self.loan_principal
        )
        if tentative_outstanding > flt(allowed.get('principal')):
            frappe.throw(
                "Customer already has existing loans. "
                "Total principal would exceed allowed {}".format(
                    _fmt_money(allowed.get('principal')),
                )
            )

    def onload(self):
        self.set_onload(
            'address_text', _make_address_text(self.customer)
        )
        if self.docstatus == 1:
            self.set_onload(
                'chart_data', get_chart_data(self.name)
            )

    def before_save(self):
        # set Loan Plan values
        rate_of_interest, rate_of_late_charges, calculation_slab = \
            frappe.get_value(
                'Microfinance Loan Plan',
                self.loan_plan,
                [
                    'rate_of_interest',
                    'rate_of_late_charges',
                    'calculation_slab',
                ]
            )
        if not self.rate_of_interest:
            self.rate_of_interest = rate_of_interest
        if not self.rate_of_late_charges:
            self.rate_of_late_charges = rate_of_late_charges
        if not self.calculation_slab:
            self.calculation_slab = calculation_slab

        # set Loan Settings values
        interest_income_account, loan_account = frappe.get_value(
            'Microfinance Loan Settings',
            None,
            ['interest_income_account', 'loan_account']
        )
        if not self.loan_account:
            self.loan_account = loan_account
        if not self.interest_income_account:
            self.interest_income_account = interest_income_account

    def before_submit(self):
        self.disbursement_status = 'Sanctioned'
        self.recovery_status = 'Not Started'
        # set to the first of the following month
        self.billing_start_date = add_days(get_last_day(self.posting_date), 1)

    def before_update_after_submit(self):
        self.validate_allowable_amount()
