"""Sum tree data structure for efficient priority sampling.

A sum tree is a binary tree where:
- Leaf nodes store transition priorities
- Internal nodes store the sum of their children
- Root stores total priority sum

This enables O(log n) sampling and O(log n) priority updates.

Reference: Schaul et al. (2015) "Prioritized Experience Replay"
"""

import numpy as np


class SumTree:
    """Binary sum tree for O(log n) prioritized sampling.

    The tree is stored as a flat array where:
    - Index 0 is the root (total sum)
    - Leaf nodes are at indices [capacity-1, 2*capacity-1)
    - For node i: left child = 2*i+1, right child = 2*i+2, parent = (i-1)//2
    """

    def __init__(self, capacity: int):
        """Initialize the sum tree.

        Args:
            capacity: Maximum number of leaf nodes (transitions)
        """
        if capacity <= 0:
            raise ValueError(f'capacity must be positive, got {capacity}')

        self.capacity = capacity
        self._tree = np.zeros(2 * capacity - 1, dtype=np.float64)
        self._data: list[object] = [None] * capacity
        self._write_idx = 0
        self._size = 0
        self._min_priority = 0.0

    def __len__(self) -> int:
        """Return current number of stored items."""
        return self._size

    @property
    def total(self) -> float:
        """Return total priority sum (root node value)."""
        return float(self._tree[0])

    def add(self, priority: float, data: object) -> None:
        """Add an item with the given priority.

        Args:
            priority: Priority value (must be non-negative)
            data: Data to store at this leaf
        """
        if priority < 0:
            raise ValueError(f'priority must be non-negative, got {priority}')

        # Get leaf index in tree array
        tree_idx = self._write_idx + self.capacity - 1

        # Store data
        self._data[self._write_idx] = data

        old_priority = float(self._tree[tree_idx])

        # Update tree with new priority
        self._update(tree_idx, priority)

        # Advance write index (circular buffer)
        self._write_idx = (self._write_idx + 1) % self.capacity
        self._size = min(self._size + 1, self.capacity)
        self._adjust_min_priority(old_priority, priority)

    def update(self, tree_idx: int, priority: float) -> None:
        """Update priority at a specific tree index.

        Args:
            tree_idx: Index in the tree array (leaf index)
            priority: New priority value (non-negative)
        """
        if priority < 0:
            raise ValueError(f'priority must be non-negative, got {priority}')

        old_priority = float(self._tree[tree_idx])
        self._update(tree_idx, priority)
        self._adjust_min_priority(old_priority, priority)

    def _update(self, tree_idx: int, priority: float) -> None:
        """Internal update method.

        Args:
            tree_idx: Index in tree array
            priority: New priority value
        """
        # Calculate change in priority
        change = priority - self._tree[tree_idx]
        self._tree[tree_idx] = priority

        # Propagate change up to root
        while tree_idx > 0:
            tree_idx = (tree_idx - 1) // 2
            self._tree[tree_idx] += change

    def get(self, cumsum: float) -> tuple[int, float, object]:
        """Get a leaf by cumulative sum (for sampling).

        Traverses the tree to find the leaf where the cumulative sum
        of priorities up to that leaf >= cumsum.

        Args:
            cumsum: Cumulative sum value in [0, total)

        Returns:
            Tuple of (tree_idx, priority, data)
        """
        if self._size == 0:
            raise ValueError('Cannot sample from empty tree')

        # Clamp cumsum to valid range
        cumsum = max(0.0, min(cumsum, self.total - 1e-10))

        # Start at root
        idx = 0

        # Traverse to leaf
        while idx < self.capacity - 1:  # While not a leaf
            left_idx = 2 * idx + 1
            right_idx = left_idx + 1

            # Check bounds
            if left_idx >= len(self._tree):
                break

            if cumsum <= self._tree[left_idx]:
                idx = left_idx
            else:
                cumsum -= self._tree[left_idx]
                idx = right_idx

        # Convert tree index to data index
        data_idx = idx - (self.capacity - 1)

        return idx, self._tree[idx], self._data[data_idx]

    def get_leaf_idx(self, tree_idx: int) -> int:
        """Convert tree index to data/leaf index.

        Args:
            tree_idx: Index in tree array

        Returns:
            Index in data array
        """
        return tree_idx - (self.capacity - 1)

    @property
    def min_priority(self) -> float:
        """Return minimum non-zero priority among stored items."""
        return float(self._min_priority)

    @property
    def max_priority(self) -> float:
        """Return maximum priority among stored items."""
        if self._size == 0:
            return 0.0

        leaf_start = self.capacity - 1
        leaf_end = leaf_start + self._size
        return float(np.max(self._tree[leaf_start:leaf_end]))

    def _adjust_min_priority(self, old_priority: float, new_priority: float) -> None:
        if self._size == 0:
            self._min_priority = 0.0
            return
        if new_priority > 0 and (self._min_priority == 0.0 or new_priority < self._min_priority):
            self._min_priority = float(new_priority)
            return
        if old_priority == self._min_priority and new_priority != old_priority:
            self._recompute_min_priority()

    def _recompute_min_priority(self) -> None:
        if self._size == 0:
            self._min_priority = 0.0
            return
        leaf_start = self.capacity - 1
        leaf_end = leaf_start + self._size
        leaf_priorities = self._tree[leaf_start:leaf_end]
        nonzero = leaf_priorities[leaf_priorities > 0]
        self._min_priority = float(np.min(nonzero)) if len(nonzero) else 0.0
