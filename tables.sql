create table properties (
    id bigint not null primary key,
    location geography(Point) not null,
    address text,
    price smallint not null,
    bedrooms smallint,
    bathrooms smallint
);

create table stations (
	id varchar(3) not null primary key,
	location geography(Point) not null,
	name text not null
);

create type journey_type as enum ('DEPART', 'ARRIVE', 'NONE');

create type day_of_week as enum (
    'SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'
);

create table journeys (
    origin varchar(3) references stations(id),
    destination varchar(3), -- might be a special group, not a station
    start_time time,
    start_type journey_type,
    return_time time,
    return_type journey_type,
    day_of_week day_of_week,
    rail_card varchar(3),
    checked_at timestamp without time zone not null default now(),
    data jsonb not null,
    primary key (origin, destination, start_time, start_type, return_time, return_type, day_of_week, rail_card)
);

CREATE INDEX properties_location ON properties USING GIST (location);

CREATE INDEX stations_location ON stations USING GIST (location);