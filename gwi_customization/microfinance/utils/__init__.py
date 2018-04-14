# -*- coding: utf-8 -*-
# Copyright (c) 2018, Libermatic and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import math
import frappe
from frappe.utils import flt


def get_gle_by(voucher_type):
    """
        Build a function that returns GL Entries of a particular voucher_type
    """
    def fn(voucher_no):
        return frappe.db.sql(
            """
                SELECT
                    account,
                    SUM(debit) AS debit,
                    SUM(credit) AS credit,
                    against,
                    against_voucher
                FROM `tabGL Entry`
                WHERE voucher_type='{type}' AND voucher_no='{no}'
                GROUP BY account
                ORDER BY account ASC
            """.format(type=voucher_type, no=voucher_no),
            as_dict=1
        )
    return fn


def interest(amount, rate=0.0, slab=0.0):
    """
        Return slabbed interest

        :param amount: Amount for which interest is to be calculated
        :param rate: Rate of interest in %
        :param slab: Discrete steps of amount on which interest is calculated
    """
    if slab:
        return (math.ceil(flt(amount) / slab) * slab) * rate / 100.0
    return amount * flt(rate) / 100.0
