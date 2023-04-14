CREATE TABLE IF NOT EXISTS `avitoreminder`.`users`(
    id int NOT NULL AUTO_INCREMENT,
    email text NOT NULL,
    password text NOT NULL,
    bot_key text NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS `avitoreminder`.`requests`(
    id int NOT NULL AUTO_INCREMENT,
    user_id integer NOT NULL,
    title text NOT NULL,
    price_from integer NULL,
    price_up_to integer NULL,
    add_description text NULL,
    city text NULL,
    delivery TINYINT NULL,
    exception text NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS `avitoreminder`.`parsing_data`(
    id int NOT NULL AUTO_INCREMENT,
    user_id integer NOT NULL,
    request_id integer NOT NULL,
    link text NOT NULL,
    title text NOT NULL,
    price integer NOT NULL,
    state text NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS `avitoreminder`.`user_state`(
    id int NOT NULL AUTO_INCREMENT,
    user_id integer NOT NULL,
    state text NOT NULL,
    last_online text NOT NULL,
    last_auth text NOT NULL,
    PRIMARY KEY (id) 
)
