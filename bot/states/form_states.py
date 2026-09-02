from aiogram.fsm.state import State, StatesGroup


class Onboarding(StatesGroup):
    phone = State()


class OrderForm(StatesGroup):
    direction = State()
    custom_time = State()
    seats = State()
    cargo_type = State()
    contact = State()


class DriverReg(StatesGroup):
    full_name = State()
    car_model = State()
    car_number = State()
    phone = State()


class ReturnTripForm(StatesGroup):
    direction = State()
    from_region = State()
    from_district = State()
    from_custom = State()
    to_region = State()
    to_district = State()
    to_custom = State()
    departure_date = State()
    custom_datetime = State()
    seats = State()
    price = State()


class BrowseTrips(StatesGroup):
    from_region = State()
    from_custom = State()
    to_location = State()
    to_custom = State()
    contact = State()


class AdminGrant(StatesGroup):
    waiting_query = State()
    waiting_days = State()
