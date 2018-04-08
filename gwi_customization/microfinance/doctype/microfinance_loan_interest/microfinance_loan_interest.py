# -*- coding: utf-8 -*-
# Copyright (c) 2018, Libermatic and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
from frappe.model.document import Document


class MicrofinanceLoanInterest(Document):
    def autoname(self):
        self.name = self.loan + '/' + self.period