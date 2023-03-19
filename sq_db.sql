CREATE TABLE IF NOT EXISTS `avitoreminder`.`users`(
    id integer PRIMARY KEY,
    email text NOT NULL,
    password text NOT NULL,
    bot_key text NOT NULL
);

CREATE TABLE IF NOT EXISTS `avitoreminder`.`requests`(
    id integer PRIMARY KEY,
    user_id integer NOT NULL,
    title text NOT NULL,
    price integer NULL,
    add_description text NULL,
    exception text NULL
);

CREATE TABLE IF NOT EXISTS `avitoreminder`.`parsing_data`(
    id integer PRIMARY KEY,
    user_id integer NOT NULL,
    link text NOT NULL,
    title text NOT NULL,
    price integer NOT NULL
)
