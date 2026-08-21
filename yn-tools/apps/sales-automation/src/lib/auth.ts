import { cookies } from "next/headers";
import { prisma } from "./prisma";
import bcrypt from "bcryptjs";

const SESSION_COOKIE = "session_user_id";

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, 10);
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

export async function createUser(username: string, password: string) {
  const hashedPassword = await hashPassword(password);
  return prisma.user.create({ data: { username, hashedPassword } });
}

export async function authenticate(username: string, password: string) {
  const user = await prisma.user.findUnique({ where: { username } });
  if (!user) return null;
  const valid = await verifyPassword(password, user.hashedPassword);
  return valid ? user : null;
}

export async function getSessionUser() {
  const cookieStore = await cookies();
  const sessionId = cookieStore.get(SESSION_COOKIE)?.value;
  if (!sessionId) return null;
  const userId = parseInt(sessionId, 10);
  if (isNaN(userId)) return null;
  return prisma.user.findUnique({ where: { id: userId } });
}

export async function getUserCount() {
  return prisma.user.count();
}

export { SESSION_COOKIE };
