-- Corre una sola vez al crear la base del banco (init-scripts de supabase/postgres): le pone contraseña al rol con
-- el que GoTrue entra a su esquema `auth`. La contraseña es la SINTÉTICA de esta corrida (nunca escrita aquí).
\set pgpass `echo "$POSTGRES_PASSWORD"`
ALTER USER supabase_auth_admin WITH PASSWORD :'pgpass';
