// Copyright (c) 2018, Libermatic and contributors
// For license information, please see license.txt

frappe.ui.form.on('Microfinance Recovery', {
  refresh: function(frm) {
    frm.fields_dict['loan'].get_query = doc => ({
      filters: { docstatus: 1 },
    });
    frappe.ui.form.on('Microfinance Other Charge', {
      charge_amount: function(frm) {
        frm.trigger('calculate_totals');
      },
      charges_remove: function(frm) {
        frm.trigger('calculate_totals');
      },
    });
  },
  loan: function(frm) {
    frm.trigger('set_init_amounts');
  },
  posting_date: function(frm) {
    frm.trigger('set_init_amounts');
  },
  principal_amount: function(frm) {
    frm.trigger('calculate_totals');
  },
  total_interests: function(frm) {
    frm.trigger('calculate_totals');
  },
  mode_of_payment: async function(frm) {
    const { mode_of_payment, company } = frm.doc;
    frm.toggle_reqd(['cheque_no', 'cheque_date'], mode_of_payment == 'Cheque');
    const { message } = await frappe.call({
      method:
        'erpnext.accounts.doctype.sales_invoice.sales_invoice.get_bank_cash_account',
      args: { mode_of_payment, company },
    });
    if (message) {
      frm.set_value('payment_account', message.account);
    }
  },
  set_init_amounts: async function(frm) {
    const { loan, posting_date } = frm.doc;
    if (loan && posting_date) {
      const [
        { message: interest_amount = 0 },
        { message: { recovery_amount = 0 } = {} },
      ] = await Promise.all([
        frappe.call({
          method:
            'gwi_customization.microfinance.api.interest.get_current_interest',
          args: { loan, posting_date },
        }),
        frappe.db.get_value('Microfinance Loan', loan, 'recovery_amount'),
      ]);
      frm.set_value('total_interests', interest_amount);
      frm.set_value('principal_amount', recovery_amount);
    }
  },
  calculate_totals: function(frm) {
    if (
      frm.fields_dict['total_interests'] &&
      frm.fields_dict['total_charges']
    ) {
      const {
        total_interests = 0,
        principal_amount = 0,
        charges = [],
      } = frm.doc;
      const total_amount = total_interests + principal_amount;
      const total_charges = charges.reduce(
        (a, { charge_amount: x = 0 }) => a + x,
        0
      );
      frm.set_value('total_amount', total_interests + principal_amount);
      frm.set_value('total_charges', total_charges);
      frm.set_value('total_received', total_amount + total_charges);
    }
  },
});
