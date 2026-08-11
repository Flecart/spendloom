export type ExpenseStatus = "queued" | "processing" | "needs_review" | "accepted" | "duplicate" | "failed" | "cancelled";
export type Scope = "personal" | "business" | "unknown";

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
  created_at: string;
  updated_at: string;
}

export interface Category { id: string; code: string; name: string; scope: Scope; color: string; icon: string; quickbooks_category: string | null; archived: boolean; }
export interface PaymentMethod { id: string; name: string; method_type: string; last_four: string | null; is_default: boolean; archived: boolean; }
export interface MerchantRule { id: string; merchant_display: string; merchant_normalized: string; category_id: string | null; category_name: string | null; payment_method_id: string | null; payment_method_name: string | null; scope: Scope | null; enabled: boolean; conflict_count: number; }
export interface Dashboard { month_total: string; previous_month_total: string; range_total: string; previous_range_total: string; date_from: string; date_to: string; review_count: number; failed_count: number; receipt_count: number; by_category: {name: string; color: string; amount: number}[]; by_month: {month: string; amount: number}[]; top_merchants: {merchant: string; amount: number}[]; }
export interface AppSettings { owner_name: string; owner_email: string; review_mode: string; confidence_threshold: number; telegram_claim_code: string; telegram_claimed: boolean; telegram_allowlist_configured: boolean; ai_provider: string; ai_model: string; ai_configured: boolean; base_currency: string; }
export interface Ingestion { id: string; expense_id: string | null; source: string; external_id: string; status: ExpenseStatus; attempts: number; error_code: string | null; error_message: string | null; received_at: string; processed_at: string | null; }

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

export const money = (value: string | number | null | undefined, currency = "EUR") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value || 0));
