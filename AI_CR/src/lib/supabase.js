import { createClient } from '@supabase/supabase-js'

// Publishable (anon) key only. It grants nothing on the app's tables: all data
// goes through the backend, which checks the signed-in user is a CR.
const url = import.meta.env.VITE_SUPABASE_URL
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

export const supabaseConfigured = Boolean(url && publishableKey)

export const supabase = supabaseConfigured
  ? createClient(url, publishableKey, { auth: { persistSession: true, autoRefreshToken: true } })
  : null
