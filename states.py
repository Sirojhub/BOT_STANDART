from aiogram.fsm.state import State, StatesGroup

class Registration(StatesGroup):
    """
    FSM States for the User Registration Flow.
    """
    choosing_language = State()
    waiting_for_webapp = State()
    waiting_for_phone = State()
    main_menu = State()  # Added for post-registration state
