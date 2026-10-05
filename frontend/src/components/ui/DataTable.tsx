import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Alert, Button, EmptyState, Skeleton } from "./controls";
export interface Column<T> {
  id: string;
  label: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number;
}
type Sort = { id: string; direction: 1 | -1 } | null;

function compareValues(left: string | number, right: string | number) {
  if (typeof left === "number" && typeof right === "number")
    return left - right;
  return String(left).localeCompare(String(right), "ru");
}

function useSortedRows<T>(columns: Column<T>[], rows: T[], sort: Sort) {
  return useMemo(() => {
    const column = columns.find((column) => column.id === sort?.id);
    const value = column?.sortValue;
    if (!sort || !value) return rows;
    return [...rows].sort(
      (a, b) => compareValues(value(a), value(b)) * sort.direction,
    );
  }, [columns, rows, sort]);
}

function ariaSort(columnId: string, sort: Sort) {
  if (sort?.id !== columnId) return undefined;
  return sort.direction === 1 ? "ascending" : "descending";
}

function nextSort(columnId: string, sort: Sort): NonNullable<Sort> {
  const descending = sort?.id === columnId && sort.direction === 1;
  return { id: columnId, direction: descending ? -1 : 1 };
}

function SortIndicator({ direction }: { direction: 1 | -1 | undefined }) {
  if (!direction) return null;
  return direction === 1 ? (
    <ArrowUp size={14} aria-hidden="true" />
  ) : (
    <ArrowDown size={14} aria-hidden="true" />
  );
}

function ColumnHeader<T>({
  column,
  sort,
  onSort,
}: {
  column: Column<T>;
  sort: Sort;
  onSort: (value: NonNullable<Sort>) => void;
}) {
  const direction = sort?.id === column.id ? sort.direction : undefined;
  return (
    <th scope="col" aria-sort={ariaSort(column.id, sort)}>
      {column.sortValue ? (
        <Button
          variant="ghost"
          onClick={() => onSort(nextSort(column.id, sort))}
        >
          {column.label}
          <SortIndicator direction={direction} />
        </Button>
      ) : (
        column.label
      )}
    </th>
  );
}
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  empty = "Записей пока нет",
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  error?: string | null;
  empty?: string;
  caption: string;
}) {
  const [sort, setSort] = useState<Sort>(null);
  const visible = useSortedRows(columns, rows, sort);
  if (loading) return <Skeleton label={`Загрузка: ${caption}`} rows={4} />;
  if (error) return <Alert>{error}</Alert>;
  if (!rows.length) return <EmptyState title={empty} />;
  return (
    <div className="data-table">
      <table>
        <caption className="sr-only">
          {caption}. Сортировка применяется к загруженной странице.
        </caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <ColumnHeader
                key={column.id}
                column={column}
                sort={sort}
                onSort={setSort}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.id} data-label={column.label}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Pagination({
  offset,
  size,
  count,
  loading,
  onChange,
}: {
  offset: number;
  size: number;
  count: number;
  loading?: boolean;
  onChange: (offset: number) => void;
}) {
  return (
    <nav
      aria-label="Страницы таблицы"
      className="flex flex-wrap items-center justify-end gap-3 mt-4"
    >
      <Button
        disabled={offset === 0 || loading}
        onClick={() => onChange(Math.max(0, offset - size))}
      >
        Назад
      </Button>
      <span className="text-xs text-secondary">
        Страница {Math.floor(offset / size) + 1}
      </span>
      <Button
        disabled={count < size || loading}
        onClick={() => onChange(offset + size)}
      >
        Далее
      </Button>
    </nav>
  );
}
