
CREATE TABLE IF NOT EXISTS users(
    id integer PRIMARY KEY AUTOINCREMENT,
    email text NOT NULL,
    password text NOT NULL,
    bot_key text NOT NULL
);

CREATE TABLE IF NOT EXISTS requests(
    id integer PRIMARY KEY AUTOINCREMENT,
    title text NOT NULL,
    price NULL,
    add text NULL,
    exception text NULL,
)
