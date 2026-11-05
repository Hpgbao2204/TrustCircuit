// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./LifecycleRoles.sol";

contract BudgetLedger is LifecycleRoles {
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

    // ------------------------------------------------------------------
    // Ledger-enforced cumulative RDP accounting (TNSE revision, R3.4).
    // For every asset the contract keeps the consumed fixed-point RDP vector
    // rho over a finite order set O' (<= 16 orders, 64-bit lanes packed four
    // per storage word) together with the conversion offsets
    // c_alpha = ceil(kappa * ln(1/delta) / (alpha - 1)) fixed at registration.
    // The charge of a settled Gaussian release with noise sigma and
    // sensitivity Delta is C(rho + rho_q) - C(rho), where
    // rho_q(alpha) = ceil(kappa * alpha * Delta^2 / (2 sigma^2)) and
    // C(v) = min_alpha (v(alpha) + c_alpha) for v != 0, C(0) = 0.
    // ------------------------------------------------------------------
    uint256 public constant MAX_ORDERS = 16;

    struct RdpConfig {
        uint8 orderCount;
        uint256 ordersPacked; // 8-bit lanes, increasing orders
        uint256[4] offsetsPacked; // 64-bit lanes
        uint256[4] consumedPacked; // 64-bit lanes
        bool consumedNonZero;
    }

    struct RdpParams {
        uint64 sigmaFixed;
        uint64 sensitivityFixed;
    }

    mapping(bytes32 => RdpConfig) private rdpConfigs;
    mapping(bytes32 => RdpParams) private rdpParams;

    event RdpBudgetRegistered(bytes32 indexed assetId, uint256 totalBudget, uint8 orderCount);
    event RdpCharged(bytes32 indexed assetId, bytes32 indexed requestId, uint256 reserved, uint256 charge);

    error InvalidOrders();
    error InvalidRdpParams();
    error NotRdpBudget(bytes32 assetId);
    error ChargeExceedsReservation(uint256 charge, uint256 reserved);

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

    function registerBudget(bytes32 assetId, uint256 totalBudget) external onlyCoordinator {
        if (totalBudget == 0) revert InvalidAmount();
        if (budgets[assetId].exists) revert BudgetAlreadyExists(assetId);

        budgets[assetId] = Budget({total: totalBudget, reserved: 0, used: 0, exists: true});
        emit BudgetRegistered(assetId, totalBudget);
    }

    function reserveBudget(bytes32 assetId, bytes32 requestId, uint256 amount)
        external
        onlyCoordinator
    {
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

    function consumeBudget(bytes32 assetId, bytes32 requestId, uint256 actualAmount)
        external
        onlyCoordinator
    {
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

    function releaseBudget(bytes32 assetId, bytes32 requestId)
        external
        onlyCoordinator
    {
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

    /// @param totalBudget floor(kappa * epsilon_tot)
    /// @param orders strictly increasing Renyi orders alpha >= 2
    /// @param offsets c_alpha = ceil(kappa * ln(1/delta) / (alpha - 1)), one per order
    function registerRdpBudget(
        bytes32 assetId,
        uint256 totalBudget,
        uint8[] calldata orders,
        uint64[] calldata offsets
    ) external onlyCoordinator {
        if (totalBudget == 0) revert InvalidAmount();
        if (budgets[assetId].exists) revert BudgetAlreadyExists(assetId);
        uint256 count = orders.length;
        if (count == 0 || count > MAX_ORDERS || offsets.length != count) revert InvalidOrders();

        RdpConfig storage config = rdpConfigs[assetId];
        uint256 packedOrders;
        for (uint256 i = 0; i < count; i++) {
            if (orders[i] < 2 || (i > 0 && orders[i] <= orders[i - 1])) revert InvalidOrders();
            if (offsets[i] == 0) revert InvalidOrders();
            packedOrders |= uint256(orders[i]) << (8 * i);
            config.offsetsPacked[i / 4] |= uint256(offsets[i]) << (64 * (i % 4));
        }
        config.orderCount = uint8(count);
        config.ordersPacked = packedOrders;
        budgets[assetId] = Budget({total: totalBudget, reserved: 0, used: 0, exists: true});
        emit BudgetRegistered(assetId, totalBudget);
        emit RdpBudgetRegistered(assetId, totalBudget, uint8(count));
    }

    /// @notice Reserves b_req = max_alpha rho_q(alpha) + [rho == 0] * min_alpha c_alpha,
    /// which bounds the settlement charge under every settlement order.
    function reserveRdp(
        bytes32 assetId,
        bytes32 requestId,
        uint64 sigmaFixed,
        uint64 sensitivityFixed
    ) external onlyCoordinator returns (uint256 amount) {
        Budget storage budget = _budgetOf(assetId);
        RdpConfig storage config = rdpConfigs[assetId];
        if (config.orderCount == 0) revert NotRdpBudget(assetId);
        if (sigmaFixed == 0 || sensitivityFixed == 0) revert InvalidRdpParams();
        if (reservations[requestId].status != ReservationStatus.None) {
            revert InvalidReservationState(requestId, reservations[requestId].status);
        }
        uint256 count = config.orderCount;
        uint256 maxOrder = uint8(config.ordersPacked >> (8 * (count - 1)));
        amount = _increment(maxOrder, sigmaFixed, sensitivityFixed);
        if (!config.consumedNonZero) {
            uint256[4] memory offsets = _load(config.offsetsPacked, count);
            uint256 minOffset = type(uint256).max;
            for (uint256 i = 0; i < count; i++) {
                uint256 offset = _lane(offsets, i);
                if (offset < minOffset) minOffset = offset;
            }
            amount += minOffset;
        }
        uint256 remainingBudget = budget.total - budget.reserved - budget.used;
        if (amount > remainingBudget) revert InsufficientBudget(assetId, amount, remainingBudget);

        budget.reserved += amount;
        reservations[requestId] = Reservation({
            assetId: assetId,
            amount: amount,
            reserver: msg.sender,
            status: ReservationStatus.Reserved
        });
        rdpParams[requestId] = RdpParams(sigmaFixed, sensitivityFixed);
        emit BudgetReserved(assetId, requestId, amount);
    }

    /// @notice Settles an RDP reservation: adds rho_q to the consumed vector and
    /// charges C(rho + rho_q) - C(rho); the unused remainder returns to the pool.
    function consumeRdp(bytes32 assetId, bytes32 requestId)
        external
        onlyCoordinator
        returns (uint256 charge)
    {
        Budget storage budget = _budgetOf(assetId);
        Reservation storage reservation = reservations[requestId];
        if (reservation.assetId != assetId) revert InvalidReservation(requestId);
        if (reservation.status != ReservationStatus.Reserved) {
            revert InvalidReservationState(requestId, reservation.status);
        }
        if (reservation.reserver != msg.sender) {
            revert UnauthorizedReservationConsumer(requestId, msg.sender);
        }
        RdpConfig storage config = rdpConfigs[assetId];
        RdpParams memory params = rdpParams[requestId];
        if (config.orderCount == 0 || params.sigmaFixed == 0) revert NotRdpBudget(assetId);

        uint256 count = config.orderCount;
        uint256[4] memory consumed = _load(config.consumedPacked, count);
        uint256[4] memory offsets = _load(config.offsetsPacked, count);
        uint256 orders = config.ordersPacked;
        bool wasNonZero = config.consumedNonZero;
        uint256 before = type(uint256).max;
        uint256 afterValue = type(uint256).max;
        for (uint256 i = 0; i < count; i++) {
            uint256 current = _lane(consumed, i);
            uint256 offset = _lane(offsets, i);
            uint256 next = current +
                _increment(uint8(orders >> (8 * i)), params.sigmaFixed, params.sensitivityFixed);
            if (next > type(uint64).max) revert InvalidAmount();
            if (current + offset < before) before = current + offset;
            if (next + offset < afterValue) afterValue = next + offset;
            consumed[i / 4] = (consumed[i / 4] & ~(uint256(type(uint64).max) << (64 * (i % 4))))
                | (next << (64 * (i % 4)));
        }
        if (!wasNonZero) before = 0;
        charge = afterValue - before;
        if (charge > reservation.amount) revert ChargeExceedsReservation(charge, reservation.amount);

        for (uint256 w = 0; w <= (count - 1) / 4; w++) {
            config.consumedPacked[w] = consumed[w];
        }
        if (!wasNonZero) config.consumedNonZero = true;
        budget.reserved -= reservation.amount;
        budget.used += charge;
        reservation.status = ReservationStatus.Consumed;
        emit BudgetConsumed(assetId, requestId, charge);
        emit RdpCharged(assetId, requestId, reservation.amount, charge);
    }

    function getRdpState(bytes32 assetId)
        external
        view
        returns (uint8[] memory orders, uint64[] memory offsets, uint64[] memory consumed)
    {
        RdpConfig storage config = rdpConfigs[assetId];
        uint256 count = config.orderCount;
        orders = new uint8[](count);
        offsets = new uint64[](count);
        consumed = new uint64[](count);
        for (uint256 i = 0; i < count; i++) {
            orders[i] = uint8(config.ordersPacked >> (8 * i));
            offsets[i] = uint64(_lane(config.offsetsPacked, i));
            consumed[i] = uint64(_lane(config.consumedPacked, i));
        }
    }

    function _increment(uint256 alpha, uint64 sigmaFixed, uint64 sensitivityFixed)
        private
        pure
        returns (uint256)
    {
        uint256 numerator = EPSILON_SCALE * alpha * uint256(sensitivityFixed) * uint256(sensitivityFixed);
        uint256 denominator = 2 * uint256(sigmaFixed) * uint256(sigmaFixed);
        return (numerator + denominator - 1) / denominator;
    }

    /// @dev Loads only the ceil(count/4) storage words that hold active lanes.
    function _load(uint256[4] storage words, uint256 count)
        private
        view
        returns (uint256[4] memory out)
    {
        for (uint256 w = 0; w <= (count - 1) / 4; w++) out[w] = words[w];
    }

    function _lane(uint256[4] memory words, uint256 i) private pure returns (uint256) {
        return uint64(words[i / 4] >> (64 * (i % 4)));
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
