-- Minimal stand-ins for the roles and auth schema that Supabase provides, so the
-- real migrations run unchanged in a plain Postgres container.
create role anon nologin noinherit;
create role authenticated nologin noinherit;
create role service_role nologin noinherit bypassrls;
create role authenticator login password 'authenticator' noinherit;
grant anon, authenticated, service_role to authenticator;

grant usage on schema public to anon, authenticated, service_role;
-- Supabase grants new public tables to anon/authenticated by default; mirror
-- that so the migration's REVOKEs are actually exercised.
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;

create schema auth;
create table auth.users (id uuid primary key, email text);
