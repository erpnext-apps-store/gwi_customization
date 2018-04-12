// Copyright (c) 2018, Libermatic and contributors
// For license information, please see license.txt

function calculate_totals(frm) {
  const { amount = 0, recovered_amount = 0, charges = [] } = frm.doc;
  frm.set_value('total_disbursed', amount - recovered_amount);
  frm.set_value(
    'total_charges',
    charges.reduce((a, { charge_amount: x = 0 }) => a + x, 0)
  );
}

frappe.ui.form.on('Microfinance Disbursement', {
  refresh: function(frm) {
    frm.fields_dict['loan'].get_query = doc => ({
      filters: { docstatus: 1 },
    });
    frappe.ui.form.on('Microfinance Other Charge', {
      charge_amount: calculate_totals,
      charges_remove: calculate_totals,
    });
  },
  loan: async function(frm) {
    const { loan } = frm.doc;
    if (loan) {
      const { message: amount } = await frappe.call({
        method:
          'gwi_customization.microfinance.api.loan.get_undisbursed_principal',
        args: { loan },
      });
      frm.set_value('amount', amount);
    }
  },
  amount: calculate_totals,
  recovered_amount: calculate_totals,
  is_opening: function(frm) {
    if (!frm.doc['is_opening']) {
      frm.set_value('recovered_amount', null);
    }
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
});
