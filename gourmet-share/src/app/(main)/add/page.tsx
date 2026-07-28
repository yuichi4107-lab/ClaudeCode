import { RestaurantForm } from '@/components/restaurant/RestaurantForm';

export default function AddPage() {
  return (
    <div className="px-4 pt-4">
      <h1 className="mb-4 text-xl font-bold">お店を登録</h1>
      <RestaurantForm />
    </div>
  );
}
