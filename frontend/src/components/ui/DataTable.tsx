import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Alert, Button, EmptyState, Skeleton } from "./controls";
export interface Column<T> {
  id: string;
  label: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number;
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
  const [sort, setSort] = useState<{ id: string; direction: 1 | -1 } | null>(
    null,
  );
  const visible = useMemo(() => {
    const column = columns.find((column) => column.id === sort?.id);
    if (!sort || !column?.sortValue) return rows;
    return [...rows].sort((a, b) => {
      const left = column.sortValue!(a),
        right = column.sortValue!(b);
      return (
        (typeof left === "number" && typeof right === "number"
          ? left - right
          : String(left).localeCompare(String(right), "ru")) * sort.direction
      );
    });
  }, [columns, rows, sort]);
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
              <th
                key={column.id}
                scope="col"
                aria-sort={
                  sort?.id === column.id
                    ? sort.direction === 1
                      ? "ascending"
                      : "descending"
                    : undefined
                }
              >
                {column.sortValue ? (
                  <Button
                    variant="ghost"
                    onClick={() =>
                      setSort({
                        id: column.id,
                        direction:
                          sort?.id === column.id && sort.direction === 1
                            ? -1
                            : 1,
                      })
                    }
                  >
                    {column.label}
                    {sort?.id === column.id &&
                      (sort.direction === 1 ? (
                        <ArrowUp size={14} aria-hidden="true" />
                      ) : (
                        <ArrowDown size={14} aria-hidden="true" />
                      ))}
                  </Button>
                ) : (
                  column.label
                )}
              </th>
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
