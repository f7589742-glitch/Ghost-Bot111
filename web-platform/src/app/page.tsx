import { redirect } from "next/navigation";

export default async function Home(props: {
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }> | { [key: string]: string | string[] | undefined };
}) {
  const sp = props.searchParams ? await props.searchParams : {};
  if (sp && sp.code) {
    redirect(`/auth/callback?code=${encodeURIComponent(String(sp.code))}`);
  }
  if (sp && sp.error) {
    redirect(
      `/login?error=${encodeURIComponent(String(sp.error))}&error_description=${encodeURIComponent(
        String(sp.error_description || sp.error)
      )}`
    );
  }
  redirect("/dashboard");
}
