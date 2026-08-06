// Edge Function for Registering Student and Parent
// @ts-ignore
import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
// @ts-ignore
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// @ts-ignore
const supabaseUrl = Deno.env.get('SUPABASE_URL') || '';
// @ts-ignore
const supabaseServiceRoleKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') || '';
const supabase = createClient(supabaseUrl, supabaseServiceRoleKey);

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

// @ts-ignore
serve(async (req: Request) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders });
  }

  try {
    const { studentName, classLevel, age, gender, parentName, parentCnic, parentEmail, schoolId } = await req.json();

    if (!studentName || !classLevel || !parentName || !parentCnic || !schoolId) {
      throw new Error('Missing required fields');
    }

    // 1. Generate Parent Password (CNIC)
    const generatedPassword = parentCnic;

    // 2. Generate Student Secret Key (Smart Collision Resistance)
    const classNum = (classLevel as string).match(/\d+/)?.[0] || '1';
    const baseKey = ((studentName as string).toLowerCase().split(' ')[0] + classNum).toUpperCase();

    let secretKey = baseKey;

    // Check if base key exists
    const { data: existingKey } = await supabase
      .from('children')
      .select('secret_key')
      .eq('secret_key', secretKey)
      .maybeSingle();

    if (existingKey) {
      // Append CNIC suffix for family-based uniqueness
      const cnicSuffix = parentCnic.slice(-4);
      secretKey = `${baseKey}-${cnicSuffix}`;

      // Final collision check (e.g. for twins)
      const { data: finalKeyCheck } = await supabase
        .from('children')
        .select('secret_key')
        .eq('secret_key', secretKey)
        .maybeSingle();

      if (finalKeyCheck) {
        secretKey = `${secretKey}-2`;
      }
    }

    // 3. Find or Create Parent
    let parentId: string | undefined = undefined;

    // Search by CNIC first
    const { data: existingParentByCnic } = await supabase
      .from('parent_profiles')
      .select('id, email')
      .eq('cnic', parentCnic)
      .maybeSingle();

    if (existingParentByCnic) {
      parentId = existingParentByCnic.id;
    } else {
      if (parentEmail) {
        const { data: existingParentByEmail } = await supabase
          .from('parent_profiles')
          .select('id')
          .eq('email', parentEmail)
          .maybeSingle();

        if (existingParentByEmail) {
          parentId = existingParentByEmail.id;
        }
      }
    }

    if (!parentId) {
      const finalEmail = parentEmail || `${parentCnic}@VisioLab.com`;
      const { data: authUser, error: authError } = await supabase.auth.admin.createUser({
        email: finalEmail,
        password: generatedPassword,
        email_confirm: true,
        user_metadata: { full_name: parentName, cnic: parentCnic }
      });

      if (authError || !authUser?.data?.user) {
        // If user already exists in auth but not in profiles
        if (authError?.message?.includes('already exists')) {
          const { data: existingUser, error: listError } = await supabase.auth.admin.listUsers();
          if (listError) throw listError;
          const match = existingUser?.users?.find((u: any) => u.email === finalEmail);
          if (match) {
            parentId = match.id;
            await supabase.auth.admin.updateUserById(parentId, { password: generatedPassword });
          } else {
            throw authError;
          }
        } else {
          throw authError || new Error('Auth creation failed');
        }
      } else {
        parentId = authUser.data.user.id;
      }

      const { error: profileError } = await supabase.from('parent_profiles').upsert([{
        id: parentId,
        full_name: parentName,
        email: finalEmail,
        cnic: parentCnic,
        role: 'parent',
        payment_status: 'paid'
      }]);
      if (profileError) throw profileError;
    } else {
      // Ensure password is sync with CNIC
      const { error: updateError } = await supabase.auth.admin.updateUserById(parentId, { password: generatedPassword });
      if (updateError) console.error("Password update error:", updateError);
    }

    if (!parentId) throw new Error('Failed to resolve parent ID');

    // 4. Create Student
    const finalParentName = (parentName || '').trim() || 'Parent';

    const { data: student, error: studentError } = await supabase.from('children').insert([{
      name: studentName,
      current_level: classLevel,
      age: parseInt(String(age)) || null,
      gender: gender || null,
      secret_key: secretKey,
      parent_id: parentId,
      school_id: schoolId,
      parent_email: parentEmail || `${parentCnic}@VisioLab.com`,
      parent_cnic: parentCnic,
      parent_name: finalParentName,
      payment_status: 'pending'
    }]).select().single();

    if (studentError) throw studentError;

    return new Response(JSON.stringify({
      success: true,
      student,
      parentCredentials: {
        email: parentEmail || `${parentCnic}@VisioLab.com`,
        password: generatedPassword,
        cnic: parentCnic
      },
      secretKey
    }), {
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });

  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return new Response(JSON.stringify({ error: message }), {
      status: 400,
      headers: { ...corsHeaders, 'Content-Type': 'application/json' },
    });
  }
});



// now hekc the qork flow that wehn i add the csv that you give will save the sutdents perfectly and teh paretns cnic will thier passwrod and the uername and the student name and class will their secrt key they can login and hte access their dashabords by using these am i right ? also please revmoe the big button of the sutndet modal inteh school dhabsrod keeo teh small scrolss button opnly  made the perfect please i hope you will work like the senor most developer