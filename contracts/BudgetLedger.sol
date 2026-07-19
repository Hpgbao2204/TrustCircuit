// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract BudgetLedger {
    uint256 public constant EPSILON_SCALE = 1_000_000;

    struct Budget {
        uint256 total;
        uint256 reserved;
        uint256 used;
        bool exists;
    }

    enum ReservationStatus {
        None,
        Reserved,
        Consumed,
        Released
    }

    struct Reservation {
        bytes32 assetId;
        uint256 amount;
        address reserver;
        ReservationStatus status;
    }

    mapping(bytes32 => Budget) private budgets;
    mapping(bytes32 => Reservation) private reservations;

    event BudgetRegistered(bytes32 indexed assetId, uint256 totalBudget);
    event BudgetReserved(bytes32 indexed assetId, bytes32 indexed requestId, uint256 amount);
    event BudgetConsumed(bytes32 indexed assetId, bytes32 indexed requestId, uint256 amount);
    event BudgetReleased(bytes32 indexed assetId, bytes32 indexed requestId, uint256 amount);

    error BudgetAlreadyExists(bytes32 assetId);
    error BudgetNotFound(bytes32 assetId);
    error InvalidAmount();
    error InsufficientBudget(bytes32 assetId, uint256 requested, uint256 remaining);
    error InvalidReservation(bytes32 requestId);
    error InvalidReservationState(bytes32 requestId, ReservationStatus status);
    error UnauthorizedReservationConsumer(bytes32 requestId, address caller);

    function registerBudget(bytes32 assetId, uint256 totalBudget) external {
        if (totalBudget == 0) revert InvalidAmount();
        if (budgets[assetId].exists) revert BudgetAlreadyExists(assetId);

        budgets[assetId] = Budget({total: totalBudget, reserved: 0, used: 0, exists: true});
        emit BudgetRegistered(assetId, totalBudget);
    }

    function reserveBudget(bytes32 assetId, bytes32 requestId, uint256 amount) external {
        Budget storage budget = _budgetOf(assetId);
        if (amount == 0) revert InvalidAmount();
        if (reservations[requestId].status != ReservationStatus.None) {
            revert InvalidReservationState(requestId, reservations[requestId].status);
        }

        uint256 remainingBudget = remaining(assetId);
        if (amount > remainingBudget) {
            revert InsufficientBudget(assetId, amount, remainingBudget);
        }

        budget.reserved += amount;
        reservations[requestId] = Reservation({
            assetId: assetId,
            amount: amount,
            reserver: msg.sender,
            status: ReservationStatus.Reserved
        });

        emit BudgetReserved(assetId, requestId, amount);
    }

    function consumeBudget(bytes32 assetId, bytes32 requestId, uint256 actualAmount) external {
        Budget storage budget = _budgetOf(assetId);
        Reservation storage reservation = reservations[requestId];

        if (reservation.assetId != assetId) revert InvalidReservation(requestId);
        if (reservation.status != ReservationStatus.Reserved) {
            revert InvalidReservationState(requestId, reservation.status);
        }
        if (reservation.reserver != msg.sender) {
            revert UnauthorizedReservationConsumer(requestId, msg.sender);
        }
        if (actualAmount == 0 || actualAmount > reservation.amount) revert InvalidAmount();

        budget.reserved -= reservation.amount;
        budget.used += actualAmount;
        reservation.status = ReservationStatus.Consumed;

        emit BudgetConsumed(assetId, requestId, actualAmount);
    }

    function releaseBudget(bytes32 assetId, bytes32 requestId) external {
        Budget storage budget = _budgetOf(assetId);
        Reservation storage reservation = reservations[requestId];

        if (reservation.assetId != assetId) revert InvalidReservation(requestId);
        if (reservation.status != ReservationStatus.Reserved) {
            revert InvalidReservationState(requestId, reservation.status);
        }
        if (reservation.reserver != msg.sender) {
            revert UnauthorizedReservationConsumer(requestId, msg.sender);
        }

        uint256 amount = reservation.amount;
        budget.reserved -= amount;
        reservation.status = ReservationStatus.Released;

        emit BudgetReleased(assetId, requestId, amount);
    }

    function getBudget(bytes32 assetId)
        external
        view
        returns (uint256 total, uint256 reserved, uint256 used, uint256 budgetRemaining)
    {
        Budget storage budget = _budgetOf(assetId);
        return (budget.total, budget.reserved, budget.used, budget.total - budget.reserved - budget.used);
    }

    function getReservation(bytes32 requestId)
        external
        view
        returns (bytes32 assetId, uint256 amount, ReservationStatus status)
    {
        Reservation storage reservation = reservations[requestId];
        return (reservation.assetId, reservation.amount, reservation.status);
    }

    function remaining(bytes32 assetId) public view returns (uint256) {
        Budget storage budget = _budgetOf(assetId);
        return budget.total - budget.reserved - budget.used;
    }

    function _budgetOf(bytes32 assetId) private view returns (Budget storage budget) {
        budget = budgets[assetId];
        if (!budget.exists) revert BudgetNotFound(assetId);
    }
}
