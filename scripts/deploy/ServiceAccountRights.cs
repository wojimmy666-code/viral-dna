using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;

namespace ViralDNA.Deployment
{
    // Add one right to the current Windows identity only. Never edit users,
    // groups, passwords, deny policies or other accounts' existing rights.
    public static class ServiceAccountRights
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct LsaObjectAttributes
        {
            public int Length;
            public IntPtr RootDirectory, ObjectName;
            public uint Attributes;
            public IntPtr SecurityDescriptor, SecurityQualityOfService;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct LsaUnicodeString
        {
            public ushort Length, MaximumLength;
            public IntPtr Buffer;
        }

        [DllImport("advapi32.dll")]
        private static extern uint LsaOpenPolicy(IntPtr systemName,
            ref LsaObjectAttributes attributes, uint access, out IntPtr policy);
        [DllImport("advapi32.dll")]
        private static extern uint LsaAddAccountRights(IntPtr policy, IntPtr sid,
            [In] LsaUnicodeString[] rights, uint count);
        [DllImport("advapi32.dll")]
        private static extern uint LsaClose(IntPtr policy);
        [DllImport("advapi32.dll")]
        private static extern uint LsaNtStatusToWinError(uint status);

        private static void Check(uint status)
        {
            if (status != 0)
                throw new Win32Exception((int)LsaNtStatusToWinError(status));
        }

        public static void GrantToCurrentUser()
        {
            using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
            {
                if (identity.User == null || identity.IsSystem ||
                    !new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                    throw new InvalidOperationException("Run as the intended Windows administrator, not SYSTEM.");

                var attributes = new LsaObjectAttributes();
                attributes.Length = Marshal.SizeOf(typeof(LsaObjectAttributes));
                IntPtr policy = IntPtr.Zero, sid = IntPtr.Zero, rightBuffer = IntPtr.Zero;
                try
                {
                    // POLICY_LOOKUP_NAMES | POLICY_CREATE_ACCOUNT.
                    Check(LsaOpenPolicy(IntPtr.Zero, ref attributes, 0x00000810, out policy));
                    var sidBytes = new byte[identity.User.BinaryLength];
                    identity.User.GetBinaryForm(sidBytes, 0);
                    sid = Marshal.AllocHGlobal(sidBytes.Length);
                    Marshal.Copy(sidBytes, 0, sid, sidBytes.Length);
                    const string right = "SeServiceLogonRight";
                    rightBuffer = Marshal.StringToHGlobalUni(right);
                    var name = new LsaUnicodeString {
                        Buffer = rightBuffer,
                        Length = (ushort)(right.Length * 2),
                        MaximumLength = (ushort)((right.Length + 1) * 2)
                    };
                    Check(LsaAddAccountRights(policy, sid, new[] { name }, 1));
                }
                finally
                {
                    if (rightBuffer != IntPtr.Zero) Marshal.FreeHGlobal(rightBuffer);
                    if (sid != IntPtr.Zero) Marshal.FreeHGlobal(sid);
                    if (policy != IntPtr.Zero) LsaClose(policy);
                }
            }
        }
    }
}
