export const schemaInitializationStatements = [
    "CREATE TABLE IF NOT EXISTS \"session\" (\n  \"id\" TEXT NOT NULL,\n  \"user_account_id\" TEXT NOT NULL,\n  CONSTRAINT \"session_primary_key_2929117aecd7\" PRIMARY KEY (\"id\"),\n  CONSTRAINT \"session_foreign_key_9d52369112e0\" FOREIGN KEY (\"user_account_id\") REFERENCES \"user_account\" (\"id\") ON DELETE RESTRICT ON UPDATE RESTRICT\n);",
    "CREATE TABLE IF NOT EXISTS \"user_account\" (\n  \"date_of_birth\" TEXT,\n  \"email\" TEXT,\n  \"gender\" TEXT,\n  \"id\" TEXT NOT NULL,\n  \"name\" TEXT,\n  \"nationality\" TEXT,\n  \"passport_expiration_date\" TEXT,\n  \"passport_number\" TEXT,\n  \"password\" TEXT,\n  \"username\" TEXT,\n  CONSTRAINT \"user_account_unique_611e351af19a\" UNIQUE (\"email\" COLLATE NOCASE),\n  CONSTRAINT \"user_account_primary_key_59210168e6ea\" PRIMARY KEY (\"id\"),\n  CONSTRAINT \"user_account_unique_8d28a75f93bd\" UNIQUE (\"username\")\n);"
];
export function initializeDatabase(connection) {
    connection.pragma("foreign_keys = ON");
    connection.transaction(() => {
        for (const statement of schemaInitializationStatements)
            connection.exec(statement);
    })();
}
