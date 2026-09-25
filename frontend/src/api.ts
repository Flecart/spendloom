export type ExpenseStatus = "queued" | "processing" | "needs_review" | "accepted" | "duplicate" | "failed" | "cancelled";
export type Scope = "personal" | "business" | "unknown";

export interface ReceiptDocument {
  receipt_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  page_count: number;
  position: number;
  file_url: string;
  preview_url: string | null;
}

export interface Expense {
  id: string;
  expense_date: string | null;
  merchant: string | null;
  original_amount: string | null;
  original_currency: string | null;
  amount: string | null;
  currency: string;
  conversion_rate: string | null;
  fx_estimated: boolean;
  fx_rate_date: string | null;
  category_id: string | null;
  category_name: string | null;
  payment_method_id: string | null;
  payment_method_name: string | null;
  scope: Scope;
  location: string | null;
  department: string | null;
  trip_name: string | null;
  refundable: boolean;
  memo: string | null;
  confidence: number;
  categorization_source: string;
  category_reason: string | null;
  status: ExpenseStatus;
  quickbooks_category: string | null;
  quickbooks_class: string | null;
  quickbooks_customer_job: string | null;
  quickbooks_location: string | null;
  quickbooks_subprogram: string | null;
  quickbooks_vendor: string | null;
  receipt_id: string | null;
  receipt_filename: string | null;
  receipt_url: string | null;
  source: string | null;
  ingestion_id: string | null;
  document_count: number;
  documents: ReceiptDocument[];
  supporting_documents: SupportingDocument[];
  created_at: string;
  updated_at: string;
}

export interface Category { id: string; code: string; name: string; scope: Scope; color: string; icon: string; quickbooks_category: string | null; archived: boolean; }
export interface PaymentMethod { id: string; name: string; method_type: string; last_four: string | null; is_default: boolean; archived: boolean; }
export interface MerchantRule { id: string; merchant_display: string; merchant_normalized: string; category_id: string | null; category_name: string | null; payment_method_id: string | null; payment_method_name: string | null; scope: Scope | null; enabled: boolean; conflict_count: number; }
export interface Dashboard {
  month_total: string;
  previous_month_total: string;
  range_total: string;
  previous_range_total: string;
  date_from: string;
  date_to: string;
  review_count: number;
  failed_count: number;
  receipt_count: number;
  by_category: { id: string; name: string; color: string; amount: number }[];
  by_month: { month: string; amount: number }[];
  by_period: { date: string; amount: number }[];
  trend_granularity: "day" | "week";
  top_merchants: { merchant: string; amount: number }[];
}
export interface AppSettings {
  owner_name: string;
  owner_email: string;
  review_mode: string;
  confidence_threshold: number;
  telegram_claim_code: string;
  telegram_claimed: boolean;
  telegram_allowlist_configured: boolean;
  ai_provider: string;
  ai_model: string;
  ai_configured: boolean;
  ai_auth_label: string;
  base_currency: string;
  timezone: string;
  reminder_time: string;
  gmail_configured: boolean;
  gmail_connected: boolean;
}
export interface Ingestion { id: string; expense_id: string | null; source: string; external_id: string; status: ExpenseStatus; attempts: number; error_code: string | null; error_message: string | null; received_at: string; processed_at: string | null; document_count: number; merged_into_ingestion_id: string | null; }

export interface SupportingDocument {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  file_url: string;
}

export type IncomeKind = "salary" | "contract" | "rental" | "interest" | "refund" | "other";

export interface Income {
  id: string;
  received_date: string;
  payer: string;
  kind: IncomeKind;
  original_amount: string;
  original_currency: string;
  amount: string | null;
  currency: string;
  conversion_rate: string | null;
  fx_estimated: boolean;
  fx_rate_date: string | null;
  contract_id: string | null;
  contract_title: string | null;
  memo: string | null;
  allocated_amount: string;
  document_count: number;
  documents: SupportingDocument[];
  created_at: string;
  updated_at: string;
}

export interface Contract {
  id: string;
  title: string;
  counterparty: string;
  reference: string | null;
  start_date: string | null;
  end_date: string | null;
  status: "draft" | "active" | "ended" | "cancelled";
  notes: string | null;
  document_count: number;
  documents: SupportingDocument[];
  created_at: string;
  updated_at: string;
}

export interface Invoice {
  id: string;
  reference: string;
  client: string;
  contract_id: string | null;
  contract_title: string | null;
  issue_date: string;
  due_date: string;
  currency: string;
  subtotal: string;
  tax_amount: string;
  total: string;
  paid_amount: string;
  outstanding_amount: string;
  status: "unpaid" | "partial" | "paid" | "overdue" | "void";
  memo: string | null;
  document_count: number;
  documents: SupportingDocument[];
  created_at: string;
  updated_at: string;
}

export type RecurringEntryType = "expense" | "income";
export type RecurrenceFrequency = "weekly" | "monthly" | "quarterly" | "yearly";

export interface RecurringItem {
  id: string;
  name: string;
  entry_type: RecurringEntryType;
  counterparty: string;
  expected_amount: string | null;
  currency: string;
  frequency: RecurrenceFrequency;
  start_date: string;
  end_date: string | null;
  reminder_days_before: number;
  category_id: string | null;
  payment_method_id: string | null;
  scope: Scope;
  income_kind: IncomeKind | null;
  contract_id: string | null;
  active: boolean;
  next_due_date: string | null;
}

export interface RecurringOccurrence {
  id: string;
  recurring_item_id: string;
  recurring_item_name: string;
  entry_type: RecurringEntryType;
  counterparty: string;
  due_date: string;
  expected_amount: string | null;
  currency: string;
  status: "pending" | "completed" | "skipped";
  timing: "upcoming" | "due" | "overdue" | "completed" | "skipped";
  actual_expense_id: string | null;
  actual_income_id: string | null;
  snoozed_until: string | null;
}

export interface FinancialOverview {
  date_from: string;
  date_to: string;
  expense_total: string;
  income_total: string;
  net_cash_flow: string;
  outstanding_receivables: string;
  due_count: number;
  overdue_count: number;
  by_month: { month: string; income: number; expense: number }[];
}

export interface GmailSenderRule {
  id: string;
  sender_address: string;
  recurring_item_id: string | null;
  recurring_item_name: string | null;
  category_id: string | null;
  scope: Scope | null;
  match_window_days: number;
  enabled: boolean;
}

export interface GmailStatus {
  configured: boolean;
  connected: boolean;
  email_address: string | null;
  status: string;
  last_synced_at: string | null;
  error_message: string | null;
  sender_rules: GmailSenderRule[];
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers, credentials: "include" });
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).detail || message; } catch { /* response is not JSON */ }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export async function downloadReimbursementZip(expenseIds: string[]): Promise<void> {
  const response = await fetch("/api/exports/reimbursement.zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ expense_ids: expenseIds }),
  });
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).detail || message; } catch { /* response is not JSON */ }
    throw new Error(message);
  }
  const filename = response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)"?/i)?.[1]
    || "spendloom-reimbursement.zip";
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const money = (value: string | number | null | undefined, currency = "EUR") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value || 0));
